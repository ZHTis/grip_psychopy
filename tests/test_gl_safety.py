import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from gripflight.gl_safety import guard_context_class, guard_stimulus_class, drain, close_window, set_text_layout


class GLThreadTests(unittest.TestCase):
    def fixture(self):
        class Context:
            delete_texture=Mock()
            delete_buffer=Mock()
        gl=SimpleNamespace(current_context=object())
        original=Context.delete_texture
        guard_context_class(Context,gl)
        ctx=Context();ctx.object_space=SimpleNamespace(_doomed_textures=[],_doomed_buffers=[])
        return Context,ctx,gl,original

    def test_worker_thread_never_calls_gl_and_main_thread_drains(self):
        cls,ctx,gl,original=self.fixture()
        worker=threading.Thread(target=lambda:(ctx.delete_texture(21),ctx.delete_buffer(34)))
        worker.start();worker.join()
        original.assert_not_called()
        self.assertEqual(ctx.object_space._doomed_textures,[21])
        self.assertEqual(ctx.object_space._doomed_buffers,[34])
        handle=SimpleNamespace(context=ctx,switch_to=Mock())
        drain(SimpleNamespace(winHandle=handle))
        handle.switch_to.assert_called_once()

    def test_main_thread_keeps_original_and_guard_is_idempotent(self):
        cls,ctx,gl,original=self.fixture()
        patched=cls.delete_texture;guard_context_class(cls,gl)
        self.assertIs(cls.delete_texture,patched)
        ctx.delete_texture(8);original.assert_called_once_with(ctx,8)
        self.assertEqual(ctx.object_space._doomed_textures,[])

    def test_no_current_context_defers_instead_of_calling_gl(self):
        cls,ctx,gl,original=self.fixture();gl.current_context=None
        ctx.delete_texture(9);original.assert_not_called()
        self.assertEqual(ctx.object_space._doomed_textures,[9])

    def test_same_layout_does_not_reset_font_or_label(self):
        class Stim:
            def __init__(self):self.writes=0;self._width=.9
            @property
            def wrapWidth(self):return self._width
            @wrapWidth.setter
            def wrapWidth(self,v):self.writes+=1;self._width=v
        stim=Stim();set_text_layout(stim,wrapWidth=.9);self.assertEqual(stim.writes,0)
        set_text_layout(stim,wrapWidth=.8);self.assertEqual(stim.writes,1)


class StimulusFinalizerTests(unittest.TestCase):
    def test_worker_finalizer_queued_then_deleted_on_main(self):
        from collections import deque
        calls=[]
        class Stim:
            def __del__(self):calls.append(threading.current_thread().name)
        guard_stimulus_class(Stim)
        window=SimpleNamespace(_grip_pending_finalizers=deque(),_grip_gl_closed=False,
                               winHandle=SimpleNamespace(switch_to=Mock(),context=None))
        def worker():
            s=Stim();s.win=window
            del s
        thread=threading.Thread(target=worker);thread.start();thread.join()
        self.assertEqual(calls,[])
        self.assertEqual(len(window._grip_pending_finalizers),1)
        drain(window)
        self.assertEqual(calls,[threading.main_thread().name])
        self.assertEqual(len(window._grip_pending_finalizers),0)

    def test_finalizers_after_context_close_never_call_gl(self):
        from collections import deque
        calls=[]
        class Stim:
            def __del__(self):calls.append('unsafe')
        guard_stimulus_class(Stim)
        window=SimpleNamespace(_grip_pending_finalizers=deque(),_grip_gl_closed=False,
                               winHandle=SimpleNamespace(switch_to=Mock(),context=None),close=Mock())
        close_window(window)
        def worker():
            s=Stim();s.win=window
            del s
        thread=threading.Thread(target=worker);thread.start();thread.join()
        self.assertEqual(calls,[]);window.close.assert_called_once()
