"""Render actual preview datasets locally; no network, solver or project writes."""
import io
import threading

_render_lock = threading.RLock()


def render_preview(kind, entry, pixels=(1000, 620)):
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    with _render_lock:
        width, height = pixels
        figure = Figure(figsize=(width / 110, height / 110), dpi=110, facecolor='#FAF9F5', layout='constrained')
        FigureCanvasAgg(figure)
        axis = figure.add_subplot(111)
        axis.set_facecolor('#FFFFFF')
        axis.tick_params(labelsize=8, colors='#73726C')
        for spine in axis.spines.values():
            spine.set_color('#DDD9CF')
        if kind == 'model':
            colors = ['#C6613F', '#3F6FA0', '#4C7D3F', '#7A63B8', '#B7791F', '#A3A29B']
            labels = []
            for index, layer in enumerate(entry.get('layers', [])):
                for polygon in layer.get('polygons', []):
                    paths = []
                    for contour in polygon.get('contours', []):
                        points = np.asarray(contour, dtype=float) * 1e6
                        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
                            raise ValueError('几何轮廓无效')
                        closed = np.vstack([points, points[0]])
                        codes = [Path.MOVETO] + [Path.LINETO] * (len(points) - 1) + [Path.CLOSEPOLY]
                        paths.append(Path(closed, codes))
                    if paths:
                        patch = PathPatch(Path.make_compound_path(*paths), facecolor=colors[index % len(colors)],
                                          edgecolor='#3D3D3A', linewidth=.6, alpha=.65,
                                          label=layer['name'] if layer['name'] not in labels else None)
                        axis.add_patch(patch)
                        labels.append(layer['name'])
            axis.autoscale_view()
            axis.set_aspect('equal', adjustable='datalim')
            if entry.get('plane') == 'gds_local_xy':
                axis.set(xlabel='GDS local x (µm)', ylabel='GDS local y (µm)', title='Saved GDS pattern · local XY (not a z slice)')
            else:
                axis.set(xlabel='x (µm)', ylabel='y (µm)', title=f"Geometry XY slice · z = {entry.get('z_m', 0) * 1e6:.5g} µm")
            if labels:
                axis.legend(loc='best', fontsize=7, framealpha=.8)
            else:
                axis.text(.5, .5, 'No saved geometry on this slice', transform=axis.transAxes, ha='center', va='center', color='#73726C')
        elif kind == 'field':
            x, y = np.asarray(entry['x']), np.asarray(entry['y'])
            values = np.asarray(entry['values'], dtype=float)
            if values.shape != (len(x), len(y)) or not np.isfinite(values).all():
                raise ValueError('场数据维度或数值无效')
            mesh = axis.pcolormesh(x * 1e6, y * 1e6, values.T, shading='auto', cmap='magma', rasterized=True)
            figure.colorbar(mesh, ax=axis, label=entry.get('quantity', '|E|²'))
            axis.set_aspect('equal', adjustable='box')
            fixed = f" · {entry.get('fixed_axis', 'z')} = {entry.get('fixed_position_m', 0) * 1e6:.5g} µm"
            axis.set(xlabel=entry.get('x_axis', 'x') + ' (µm)', ylabel=entry.get('y_axis', 'y') + ' (µm)',
                     title=f"{entry.get('name', 'Field')} · λ = {entry['wavelength_m'] * 1e9:.5g} nm{fixed}")
            if entry.get('sampled'):
                axis.text(1, 1.01, 'Preview subsampled', transform=axis.transAxes, ha='right', fontsize=7, color='#73726C')
        elif kind == 'spectrum':
            wavelengths = np.asarray(entry['wavelength_m'], dtype=float)
            values = np.asarray(entry['values'], dtype=float)
            if wavelengths.ndim != 1 or values.shape != wavelengths.shape or not np.isfinite(wavelengths).all() or not np.isfinite(values).all():
                raise ValueError('光谱数据维度或数值无效')
            axis.plot(wavelengths * 1e9, values, color='#C6613F', linewidth=1.8,
                      marker='o' if len(values) <= 8 else None, markersize=5)
            axis.axhline(0, color='#A3A29B', linewidth=.6)
            axis.grid(alpha=.18)
            axis.set(xlabel='Wavelength (nm)', ylabel='Signed power transmission T', title=entry.get('name', 'Transmission'))
        else:
            raise ValueError('未知预览类型')
        buffer = io.BytesIO()
        figure.savefig(buffer, format='png', dpi=110)
        figure.clear()
        return buffer.getvalue()
