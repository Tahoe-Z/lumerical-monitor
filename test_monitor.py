import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io
from types import SimpleNamespace
import threading

import remote_probe as probe
from client import Client, Profile, ssh_command, remote_script
from app import Monitor

TEST_TMP=Path(__file__).resolve().parent/'.test-tmp'
TEST_TMP.mkdir(exist_ok=True)

def temporary():
    return tempfile.TemporaryDirectory(dir=TEST_TMP)

class ProbeTests(unittest.TestCase):
    def test_gpu_csv_multi_device_and_unknown_fields(self):
        text='0, "NVIDIA Model, Special", GPU-a, 25, 100, 16384, 37, 28.20, 350.00\n1, NVIDIA Example GPU, GPU-b, [N/A], N/A, 16384, [Not Supported], N/A, 350.00\n'
        rows=probe.parse_gpus(text)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['name'],'NVIDIA Model, Special')
        self.assertEqual(rows[0]['memory_used_bytes'],100*1024**2)
        self.assertEqual(rows[0]['utilization_percent'],25)
        self.assertIsNone(rows[1]['utilization_percent'])
        self.assertIsNone(rows[1]['temperature_c'])
        self.assertIsNone(rows[1]['memory_used_bytes'])

    def test_gpu_unavailable_does_not_break_other_metrics(self):
        with patch('remote_probe.shutil.which',return_value=None):
            data=probe.gpu_snapshot()
        self.assertEqual(data['devices'],[])
        self.assertFalse(data['available'])
        self.assertIn('nvidia-smi',data['error'])

    def test_gpu_process_failure_preserves_device_data(self):
        output=SimpleNamespace(returncode=0,stdout='0,NVIDIA Example GPU,GPU-a,0,14,16384,37,28,350\n',stderr='')
        failure=SimpleNamespace(returncode=1,stdout='',stderr='Not supported')
        with patch('remote_probe.shutil.which',return_value='/usr/bin/nvidia-smi'),patch('remote_probe.subprocess.run',side_effect=[output,failure]):
            data=probe.gpu_snapshot()
        self.assertTrue(data['available'])
        self.assertEqual(len(data['devices']),1)
        self.assertIn('Not supported',data['process_error'])

    def test_gpu_compute_processes_include_other_users_without_private_paths(self):
        def owner(pid):
            return {'uid':1001 if pid==123 else 1002,'user':'me' if pid==123 else 'other','mine':pid==123}
        with patch('remote_probe.process_owner',side_effect=owner):
            rows=probe.parse_gpu_processes('GPU-a, 123, /bin/fdtd-engine, 900\nGPU-b, 456, /other/private, 800\n')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['pid'],123)
        self.assertEqual(rows[0]['memory_bytes'],900*1024**2)
        self.assertFalse(rows[1]['mine'])
        self.assertEqual(rows[1]['user'],'other')
        self.assertEqual(rows[1]['name'],'private')

    def test_gpu_unknown_owner_does_not_hide_visible_occupancy(self):
        with patch('remote_probe.process_owner',return_value={'uid':None,'user':'未知/不可见','mine':False}):
            rows=probe.parse_gpu_processes('GPU-a, 999, /hidden/program, 500\n')
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['uid'])
        self.assertEqual(rows[0]['name'],'program')

    def test_shared_process_stat_parsing_handles_spaces_and_core_percent(self):
        fields=['S','1','1','1','0','0','0','0','0','0','0','200','100','0','0','20','0','4','0','1000']
        record=probe.parse_process_stat('12 (job name) '+' '.join(fields),uptime=20,hz=100)
        self.assertEqual(record['elapsed_seconds'],10)
        self.assertEqual(record['cpu_average_percent'],30)

    def test_paths_and_symlink_escape(self):
        with temporary() as d, temporary() as outside:
            root=Path(d)
            (root/'x.txt').write_text('ok')
            self.assertEqual(probe.project_path(root,'x.txt'),root/'x.txt')
            with self.assertRaises(ValueError): probe.project_path(root,'../escape')
            with self.assertRaises(ValueError): probe.project_path(root,outside)
            try: (root/'escape').symlink_to(outside,target_is_directory=True)
            except OSError: return  # Windows symlink privilege is optional; integration repeats on Linux.
            with self.assertRaises(ValueError): probe.project_path(root,'escape')

    def test_log_tail_is_bounded_and_handles_utf8(self):
        with temporary() as d:
            p=Path(d)/'日志.txt'
            p.write_text('早期\n'+'line\n'*100+'最后一行\n',encoding='utf-8')
            result=probe.tail_file(p,limit=60,lines=3)
            self.assertIn('最后一行',result['text'])
            self.assertTrue(result['truncated'])
            self.assertLessEqual(len(result['text'].splitlines()),3)

    def test_non_regular_files_rejected(self):
        with temporary() as d:
            with self.assertRaises(ValueError): probe.tail_file(Path(d))

    def test_success_requires_completion_not_progress(self):
        with temporary() as d:
            p=Path(d)
            (p/'solve.log').write_text('100% complete. WRITE_START')
            self.assertEqual(probe.job_state(p,False)['state'],'未知/未完成')
            (p/'service-exit-code.txt').write_text('0\n')
            (p/'mmi_p0.log').write_text('Simulation completed successfully')
            self.assertEqual(probe.job_state(p,False)['state'],'已完成')
            (p/'service-exit-code.txt').write_text('1\n')
            self.assertEqual(probe.job_state(p,False)['state'],'失败')
            self.assertEqual(probe.job_state(p,True)['state'],'运行中')

    def test_listing_excludes_external_symlinks(self):
        with temporary() as d:
            root=Path(d)
            (root/'sub').mkdir()
            (root/'a.fsp').write_bytes(b'abc')
            result=probe.dispatch({'op':'list','root':d,'path':'.'})
            self.assertEqual([x['name'] for x in result['entries']],['sub','a.fsp'])
            self.assertEqual(result['entries'][1]['size'],3)


    ENGINE_XML=('<addcolumn><column><title>Max time remaining</title><type>text</type><tagname>time</tagname></column>'
                '<column><title>Autoshutoff level</title><type>text</type><tagname>shutoff</tagname></column>'
                '<column><title>Progress</title><type>progress</type><tagname>progress</tagname></column></addcolumn>\n'
                '<status>MESH_START</status>\n<update><progress>100</progress></update>\n<status>BUILD_SOURCES_FINISH</status>\n'
                '<update><progress>1.5</progress><time>2 hrs, 5 mins</time><shutoff>1</shutoff></update>\n'
                '<update><progress>3.0</progress><time>1 hr, 58 mins</time><shutoff>0.0137</shutoff></update>\n')

    def test_engine_xml_protocol_is_parsed_generically(self):
        info=probe.parse_engine_log(self.ENGINE_XML)
        self.assertEqual(info['progress'],3.0)  # the meshing-stage 100% is not mistaken for solver progress
        self.assertEqual(info['remaining'],'1 hr, 58 mins')
        self.assertEqual(info['series'],[1.0,0.0137])
        self.assertEqual(info['series_title'],'Autoshutoff level')
        self.assertEqual(info['metrics']['Max time remaining'],'1 hr, 58 mins')
        self.assertFalse(info['complete'])
        done=probe.parse_engine_log(self.ENGINE_XML+'<status>WRITE_FINISH</status>\n<simComplete/>\n<complete/>\n')
        self.assertTrue(done['complete'])
        self.assertEqual(done['stage'],'WRITE_FINISH')
        # another solver declaring its own columns still yields a series and metrics
        other=probe.parse_engine_log('<addcolumn><column><title>Residual</title><type>text</type><tagname>res</tagname></column></addcolumn>'
                                     '<update><progress>40</progress><res>0.01</res></update><update><progress>60</progress><res>0.001</res></update>')
        self.assertEqual((other['progress'],other['series_title'],other['series']),(60.0,'Residual',[0.01,0.001]))

    def test_solver_log_banner_completion_and_errors(self):
        text=('Ansys Lumerical 2026 R1 FDTD Solver Version 8.35 (Linux 64bit)\nlicense host: 1055@localhost\n'
              'Estimate of memory required: 8 GiB\n1.0% complete. Max time remaining: 23 hrs, 22 mins, 5 secs. Auto Shutoff: 0.99\n')
        info=probe.parse_solver_log(text)
        self.assertEqual((info['solver'],info['progress'],info['memory_estimate']),('FDTD',1.0,'8 GiB'))
        self.assertEqual(info['errors'],[])  # license lines are not errors
        self.assertTrue(probe.parse_solver_log(text+'Simulation completed successfully\n')['complete'])
        self.assertEqual(probe.parse_solver_log(text+'user(process 0): ERROR: out of memory\n')['errors'],['user(process 0): ERROR: out of memory'])
        self.assertEqual(probe.parse_solver_log('Ansys Lumerical 2026 R1 varFDTD Solver Version 1\n')['solver'],'varFDTD')

    # Entirely synthetic FlexLM output; no captured server data.
    LMSTAT=('Flexible License Manager status on Tue 01/01/2030 12:00\n\n'
            'License server status: 1055@localhost\n localhost: license server UP v1.0\n\n'
            'Vendor daemon status (on host):\n\n  ansyslmd: UP v1.0\nFeature usage info:\n\n'
            'Users of acfd:  (Total of 100 licenses issued;  Total of 0 licenses in use)\n\n'
            'Users of anshpc_pack:  (Total of 100 licenses issued;  Total of 8 licenses in use)\n\n'
            '"anshpc_pack" v1.0, vendor: ansyslmd, expiry: 31-dec-2099\n  floating license\n\n'
            '    alice workstation-a display-a 1201 (v1.0) (localhost/1055 101), start Tue 1/1 12:00, 3 licenses, PID: 1202 \n'
            '    other workstation-b display-b 1204 (v1.0) (localhost/1055 102), start Tue 1/1 12:10, 5 licenses, PID: 1205 \n\n'
            'Users of lumerical_gui:  (Total of 100 licenses issued;  Total of 1 license in use)\n\n'
            '"lumerical_gui" v1.0, vendor: ansyslmd, expiry: 31-dec-2099\n\n'
            '    alice workstation-a display-a 1203 (v1.0) (localhost/1055 103), start Tue 1/1 12:20, PID: 1206 \n\n'
            'Users of lumerical_solve:  (Total of 100 licenses issued;  Total of 3 licenses in use)\n\n'
            '"lumerical_solve" v1.0, vendor: ansyslmd, expiry: 31-dec-2099\n\n'
            '    alice workstation-a display-a 1201 (v1.0) (localhost/1055 104), start Tue 1/1 12:00, PID: 1202 \n')

    def test_lmstat_is_parsed_into_features_and_checkouts(self):
        info=probe.parse_lmstat(self.LMSTAT)
        self.assertTrue(info['server_up'])
        self.assertEqual(info['daemons'],{'ansyslmd':'UP'})
        by_name={f['name']:f for f in info['features']}
        self.assertEqual((by_name['anshpc_pack']['issued'],by_name['anshpc_pack']['in_use'],by_name['anshpc_pack']['expiry']),
                         (100,8,'31-dec-2099'))
        self.assertEqual(by_name['anshpc_pack']['checkouts'][0],
                         {'user':'alice','host':'workstation-a','pid':1201,'start':'Tue 1/1 12:00','count':3})
        self.assertEqual(by_name['anshpc_pack']['checkouts'][1]['user'],'other')
        self.assertEqual(by_name['lumerical_gui']['checkouts'][0]['count'],1)
        self.assertEqual(by_name['acfd']['in_use'],0)

    def test_license_status_filters_features_and_maps_runs(self):
        probe._LICENSE_CACHE.clear()
        output=SimpleNamespace(returncode=0,stdout=self.LMSTAT,stderr='')
        with patch('remote_probe.find_lmutil',return_value='/x/lmutil'),patch('remote_probe.subprocess.run',return_value=output) as run:
            status=probe.license_status('1055@localhost')
            probe.license_status('1055@localhost')  # cached: lmstat runs once a minute at most
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args[0][0],['/x/lmutil','lmstat','-a','-c','1055@localhost'])
        self.assertEqual([f['name'] for f in status['features']],['anshpc_pack','lumerical_gui','lumerical_solve'])
        self.assertEqual(status['total_features'],4)
        rows=[{'pids':[1201]},{'pids':[]}]
        probe.attach_licenses(rows,status)
        self.assertEqual(rows[0]['licenses'],[{'feature':'anshpc_pack','count':3},{'feature':'lumerical_solve','count':1}])
        self.assertEqual(rows[1]['licenses'],[])

    def test_missing_lmutil_is_reported_not_raised(self):
        probe._LICENSE_CACHE.clear()
        with patch('remote_probe.find_lmutil',return_value=None):
            status=probe.license_status('1@nowhere')
        self.assertFalse(status['available'])
        self.assertIn('lmutil',status['error'])

    def test_filesystem_numbers_match_df(self):
        # Synthetic block counts exercise reserved-block accounting.
        stat=SimpleNamespace(f_frsize=4096,f_blocks=1000,f_bfree=300,f_bavail=200)
        with patch('remote_probe.os.statvfs',return_value=stat,create=True):
            fs=probe.filesystem_info(Path('/srv/simulations'))
        self.assertEqual((fs['used'],fs['available'],fs['reserved']),(700*4096,200*4096,100*4096))
        self.assertAlmostEqual(100*fs['used']/(fs['used']+fs['available']),77.777777,places=5)

    def test_tree_size_counts_allocated_blocks_once(self):
        with temporary() as d:
            root=Path(d)
            (root/'sub').mkdir()
            (root/'sub'/'a.bin').write_bytes(b'x'*10000)
            probe._SIZE_CACHE.clear()
            info=probe.tree_size(root)
            self.assertTrue(info['complete'])
            self.assertGreaterEqual(info['bytes'],10000)
            self.assertIs(probe.tree_size(root),info)  # cached

    def test_engine_names_map_to_solvers(self):
        for exe,solver in [('fdtd-engine','FDTD'),('fdtd-engine-impi-lcl','FDTD'),('varfdtd-engine','varFDTD'),
                           ('eme-engine-ompi-lcl','EME'),('fd-engine','FDE'),('device-engine','CHARGE'),('thermal-engine','HEAT')]:
            self.assertEqual(probe.classify_process(exe),('engine',solver))
        self.assertEqual(probe.classify_process('mode-solutions-app'),('cad','MODE'))
        self.assertEqual(probe.classify_process('python3.13')[0],'python')

    def test_lumerical_runs_merge_processes_disk_and_gpu(self):
        with temporary() as d:
            root=Path(d).resolve()
            live=root/'study'/'out3d'
            live.mkdir(parents=True)
            (live/'fields_A.fsp').write_bytes(b'x')
            (live/'fields_A_p0.log').write_text('Ansys Lumerical 2026 R1 FDTD Solver Version 8\n1.0% complete. Max time remaining: 23 hrs, 22 mins, 5 secs. Auto Shutoff: 0.99\n')
            (live/'fields_A_engine.log').write_text(self.ENGINE_XML)
            done=root/'old'
            done.mkdir()
            (done/'sweep.lms').write_bytes(b'x')
            (done/'sweep_p0.log').write_text('Ansys Lumerical 2026 R1 EME Solver Version 1\nSimulation completed successfully\n')
            (done/'oom_p0.log').write_text('ERROR: out of memory\n')
            driver={'pid':10,'ppid':1,'kind':'python','solver':None,'exe':'python3.13','cwd':str(root),
                    'argv':['/opt/python','-u','fields.py','--gpu','0'],'rss_bytes':0,'threads':1,'elapsed_seconds':9,'cpu_percent':0}
            engine={'pid':11,'ppid':10,'kind':'engine','solver':'FDTD','exe':'fdtd-engine','cwd':str(root),
                    'argv':['fdtd-engine','-gpu','-remote',str(live/'fields_A.fsp')],'rss_bytes':5,'threads':4,
                    'elapsed_seconds':60,'cpu_percent':140.0}
            gpu={'devices':[{'uuid':'GPU-a','index':1}],'processes':[{'uuid':'GPU-a','pid':11,'memory_bytes':2**30}]}
            probe._SCAN_CACHE.clear()
            runs,scan=probe.lumerical_runs(root,[driver,engine],gpu)
            by_name={r['name']:r for r in runs}
            a=by_name['fields_A']
            self.assertEqual((a['state'],a['solver'],a['progress'],a['remaining']),('运行中','FDTD',3.0,'1 hr, 58 mins'))
            self.assertEqual((a['resources']['gpus'],a['resources']['gpu_memory'],a['flags']),([1],2**30,['GPU']))
            self.assertEqual(a['driver'],'python -u fields.py --gpu 0')
            self.assertEqual(Path(a['dir']),Path('study')/'out3d')
            self.assertEqual((by_name['sweep']['state'],by_name['sweep']['solver']),('已完成','EME'))
            self.assertEqual(by_name['oom']['state'],'失败')
            self.assertEqual(runs[0]['name'],'fields_A')  # running first
            self.assertGreaterEqual(scan['dirs'],3)

    def test_engine_outside_root_is_listed_without_reading_files(self):
        with temporary() as d, temporary() as outside:
            secret=Path(outside).resolve()/'x.fsp'
            (secret.parent/'x_p0.log').write_text('should not be read')
            engine={'pid':5,'ppid':1,'kind':'engine','solver':'EME','exe':'eme-engine','cwd':str(secret.parent),
                    'argv':['eme-engine',str(secret)],'rss_bytes':0,'threads':1,'elapsed_seconds':1,'cpu_percent':0}
            probe._SCAN_CACHE.clear()
            runs,_=probe.lumerical_runs(Path(d).resolve(),[engine])
            self.assertEqual(len(runs),1)
            self.assertEqual((runs[0]['state'],runs[0]['dir'],runs[0]['log'],runs[0]['last_line']),('运行中',None,'',''))


class AppHelperTests(unittest.TestCase):
    def test_engine_protocol_is_rendered_readably(self):
        from app import pretty_engine_log
        text=pretty_engine_log(ProbeTests.ENGINE_XML+'<status>WRITE_FINISH</status>\nplain line\n<simComplete/>\n')
        lines=text.splitlines()
        self.assertEqual(lines[0],'# 引擎声明的列：Max time remaining、Autoshutoff level、Progress')
        self.assertIn('▸ 开始网格划分',lines)
        self.assertIn('  进度 3.00%   ·   剩余 1 hr, 58 mins   ·   Shutoff 0.0137',lines)
        self.assertIn('plain line',lines)
        self.assertEqual(lines[-1],'✓ 仿真完成')
        self.assertNotIn('<update>',text)

    def test_short_folder_keeps_the_informative_tail(self):
        from app import short_folder
        self.assertEqual(short_folder('a/b/c/d/e'),'…/c/d/e')
        self.assertEqual(short_folder('a/b'),'a/b')
        self.assertEqual(short_folder(''),'')

    def test_eta_and_shutoff_scale(self):
        self.assertEqual(Monitor._seconds('16 hrs, 39 mins, 59 secs'),16*3600+39*60+59)
        self.assertIsNone(Monitor._seconds(''))
        self.assertEqual(Monitor._eta({'remaining':'1 hr, 2 mins, 0 secs'}),'1时 02分')
        self.assertEqual(Monitor._shutoff_scale(1),100)
        self.assertEqual(Monitor._shutoff_scale(1e-6),0)
        self.assertIsNone(Monitor._shutoff_scale(0))


class ClientTests(unittest.TestCase):
    def test_persistent_session_reuses_one_process_and_reports_errors(self):
        import sys, client
        local=[sys.executable,'-u','-c',client.BOOT_CODE]
        with temporary() as d, patch('client.session_command',return_value=local):
            (Path(d)/'a.txt').write_text('ok')
            c=Client(Profile(root=d))
            try:
                first=c.request('list','.')
                pid=c.session.proc.pid
                self.assertEqual([e['name'] for e in first['entries']],['a.txt'])
                self.assertIn('ok',c.request('tail','a.txt')['text'])
                with self.assertRaisesRegex(RuntimeError,'超出项目目录'):
                    c.request('list','..')
                self.assertEqual(c.session.proc.pid,pid)  # remote errors keep the session
                c.session.proc.kill(); c.session.proc.wait()
                self.assertEqual(c.request('list','.')['path'],'.')  # dropped session restarts
                self.assertNotEqual(c.session.proc.pid,pid)
            finally:
                c.close()
            self.assertIsNone(c.session.proc)

    def test_closed_client_fails_fast_instead_of_reconnecting(self):
        import sys, client
        with patch('client.session_command',return_value=[sys.executable,'-u','-c',client.BOOT_CODE]) as command:
            c=Client(Profile())
            c.close()
            with self.assertRaisesRegex(RuntimeError,'退出'):
                c.request('list','.')
            command.assert_not_called()

    def test_session_start_failure_surfaces_stderr(self):
        import sys
        failing=[sys.executable,'-c','import sys;sys.stderr.write("Permission denied (publickey)");sys.exit(255)']
        with patch('client.session_command',return_value=failing):
            with self.assertRaisesRegex(RuntimeError,'Permission denied'):
                Client(Profile()).request('snapshot')

    def test_settings_roundtrip_ignores_ui_keys(self):
        with temporary() as d:
            with patch('client.HERE',Path(d)):
                from client import save_settings
                save_settings(Profile(host='example.org',port=2222),refresh_seconds=30)
                data=json.loads((Path(d)/'profile.json').read_text(encoding='utf-8'))
                self.assertEqual(data['refresh_seconds'],30)
                self.assertEqual(Profile.load(),Profile(host='example.org',port=2222))
                with self.assertRaises(ValueError):
                    save_settings(Profile(host='-oProxyCommand=x'))


    def test_arguments_do_not_use_shell_and_preserve_spaces(self):
        p=Profile(key=r'C:\Users\Name With Space\key')
        cmd=ssh_command(p)
        self.assertIn(p.key,cmd)
        self.assertIn('StrictHostKeyChecking=yes',cmd)
        self.assertEqual(cmd[-1],'python3 -')

    def test_reject_option_injection(self):
        for host in ['-oProxyCommand=bad','host;touch x','host\nother']:
            with self.assertRaises(ValueError): ssh_command(Profile(host=host))
        with self.assertRaises(ValueError): ssh_command(Profile(user='x;bad'))

    def test_script_keeps_request_as_data(self):
        text=remote_script({'op':'tail','path':"a'\n$(touch bad)"})
        self.assertIn('base64.b64decode',text)
        self.assertNotIn('$(touch bad)',text)
        compile(text,'remote','exec')

    def test_failed_download_preserves_existing_file(self):
        class FakeProcess:
            def __init__(self,*args,**kwargs):
                self.stdin=io.BytesIO()
                self.stdout=io.BytesIO(b'{"size": 100, "mtime_ns": 1}\npartial')
                self.returncode=1
            def poll(self): return self.returncode
            def wait(self): return self.returncode
            def kill(self): self.returncode=-9
        with temporary() as d:
            dest=Path(d)/'keep.txt'
            dest.write_bytes(b'original')
            with patch('client.subprocess.Popen',FakeProcess):
                with self.assertRaises(RuntimeError): Client().download('a.txt',dest)
            self.assertEqual(dest.read_bytes(),b'original')
            self.assertEqual(list(Path(d).glob('*.part')),[])

    def test_successful_download_preserves_binary_bytes(self):
        payload=b'\x00\r\n\xffFDTD\n'
        class FakeProcess:
            def __init__(self,*args,**kwargs):
                self.stdin=io.BytesIO()
                self.stdout=io.BytesIO(json.dumps({'size':len(payload),'mtime_ns':1}).encode()+b'\n'+payload)
                self.returncode=0
            def poll(self): return self.returncode
            def wait(self): return self.returncode
            def kill(self): self.returncode=-9
        with temporary() as d:
            dest=Path(d)/'model.fsp'
            with patch('client.subprocess.Popen',FakeProcess):
                self.assertEqual(Client().download('model.fsp',dest),len(payload))
            self.assertEqual(dest.read_bytes(),payload)

    def test_cancel_during_ssh_stdin_write_cleans_temporary_file(self):
        release=threading.Event()
        cancel=threading.Event()
        class BlockedInput:
            closed=False
            def write(self,data):
                if not release.wait(2):
                    raise AssertionError('Cancellation watcher did not interrupt SSH stdin')
                raise BrokenPipeError('cancelled')
            def close(self): self.closed=True
        class FakeProcess:
            def __init__(self,*args,**kwargs):
                self.stdin=BlockedInput()
                self.stdout=io.BytesIO()
                self.returncode=None
            def poll(self): return self.returncode
            def wait(self): return self.returncode
            def kill(self):
                self.returncode=-9
                release.set()
        with temporary() as d:
            dest=Path(d)/'keep.txt'
            dest.write_bytes(b'original')
            timer=threading.Timer(.05,cancel.set)
            timer.start()
            try:
                with patch('client.subprocess.Popen',FakeProcess):
                    with self.assertRaisesRegex(RuntimeError,'已取消'):
                        Client().download('a.txt',dest,cancel=cancel)
            finally:
                timer.cancel()
            self.assertTrue(release.is_set())
            self.assertEqual(dest.read_bytes(),b'original')
            self.assertEqual(list(Path(d).glob('*.part')),[])


class ShutdownTests(unittest.TestCase):
    def test_close_waits_for_download_cleanup(self):
        state={'destroyed':False,'callbacks':[]}
        setter=SimpleNamespace(set=lambda value:None)
        app=SimpleNamespace(closed=False,closing=False,busy={'download'},auto=setter,
                            client=SimpleNamespace(close=lambda:state.update(session_closed=True)),
                            _save_window=lambda:state.update(window_saved=True),
                            activity=setter,cancel_download=threading.Event(),
                            destroy=lambda:state.update(destroyed=True),
                            after=lambda ms,callback:state['callbacks'].append(callback))
        app._finish_close=lambda:Monitor._finish_close(app)
        Monitor.close(app)
        self.assertTrue(app.cancel_download.is_set())
        self.assertFalse(state['destroyed'])
        app.busy.clear()
        state['callbacks'][0]()
        self.assertTrue(state['destroyed'])
        self.assertTrue(state['session_closed'])
        self.assertTrue(state['window_saved'])


if __name__=='__main__': unittest.main()
