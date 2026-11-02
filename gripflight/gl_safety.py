"""Keep legacy pyglet GL destruction on the rendering thread.

PsychoPy's bundled pyglet 1.x uses a process-global current_context. A cyclic
GC on a serial/queue thread can therefore delete a texture without a native
current GL context. Use pyglet's existing deferred-delete queues instead.
No installed PsychoPy/pyglet files are changed.
"""
from collections import deque
import functools
import threading


def guard_context_class(context_class, gl):
    """Install once; retain pyglet's normal deletion on the main GL thread."""
    if getattr(context_class, '_grip_thread_guard', False):
        return
    for method, pending in (('delete_texture', '_doomed_textures'),
                            ('delete_buffer', '_doomed_buffers')):
        original = getattr(context_class, method)
        def wrap(original, pending):
            @functools.wraps(original)
            def delete(context, identifier):
                current = getattr(gl, 'current_context', None)
                if threading.current_thread() is not threading.main_thread() or current is None:
                    # list.append is atomic in this CPython/pyglet 1.x runtime.
                    getattr(context.object_space, pending).append(identifier)
                    return
                return original(context, identifier)
            return delete
        setattr(context_class, method, wrap(original, pending))
    context_class._grip_thread_guard = True


def install():
    import pyglet
    if not str(pyglet.version).startswith('1.'):
        return False  # Do not replace another pyglet generation's lifecycle.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Create the PsychoPy display on the main thread')
    from pyglet import gl
    from pyglet.gl.base import Context
    guard_context_class(Context, gl)
    return True


def manage_window(window, visual):
    """PsychoPy stimulus finalizers bypass pyglet's texture-deletion methods."""
    window._grip_gl_closed = False
    window._grip_pending_finalizers = deque()
    for cls in (visual.TextStim, visual.ImageStim):
        guard_stimulus_class(cls)


def guard_stimulus_class(cls):
    if getattr(cls, '_grip_finalizer_guard', False):
        return
    original = cls.__del__
    @functools.wraps(original)
    def finalize(stimulus):
        try:
            window = getattr(stimulus, 'win', None)
            pending = getattr(window, '_grip_pending_finalizers', None)
            if pending is None:
                return original(stimulus)
            if window._grip_gl_closed:
                return  # Destroying the native context has already reclaimed its resources.
            if threading.current_thread() is not threading.main_thread():
                pending.append((original, stimulus))
                return
            window.winHandle.switch_to()
            return original(stimulus)
        except ReferenceError:
            return  # The weak window reference has already been destroyed.
    cls.__del__ = finalize
    cls._grip_finalizer_guard = True


def drain(window):
    """Activate the native context and finalize resources only on the main thread."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Render and release GL resources on the main thread')
    handle = getattr(window, 'winHandle', None)
    pending = getattr(window, '_grip_pending_finalizers', ())
    if pending:
        handle.switch_to()
        while pending:
            original, stimulus = pending.popleft()
            original(stimulus)
    context = getattr(handle, 'context', None)
    space = getattr(context, 'object_space', None)
    if space is not None and (space._doomed_textures or space._doomed_buffers):
        handle.switch_to()


def close_window(window):
    drain(window)
    window._grip_gl_closed = True
    try:
        window.close()
    finally:
        # Late finalizers queued just before the closed flag need no GL calls.
        pending = getattr(window, '_grip_pending_finalizers', None)
        if pending is not None:
            pending.clear()


def set_text_layout(stimulus, **attributes):
    """Legacy TextStim wrapWidth/height setters rebuild labels even if equal."""
    for key, value in attributes.items():
        if getattr(stimulus, key, None) != value:
            setattr(stimulus, key, value)
