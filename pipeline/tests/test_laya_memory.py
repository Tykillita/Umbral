import inspect
import sys
from types import ModuleType, SimpleNamespace

from umbral_pipeline.classify.laya_clf import _configure_cpu_threads, _load_laya_agent


def test_laya_cpu_threads_are_capped_and_configurable(monkeypatch):
    configured = {}
    fake_torch = SimpleNamespace(
        set_num_threads=lambda value: configured.update(intra=value),
        set_num_interop_threads=lambda value: configured.update(inter=value),
    )
    monkeypatch.setenv("UMBRAL_LAYA_CPU_THREADS", "3")

    assert _configure_cpu_threads(fake_torch) == 3
    assert configured == {"intra": 3, "inter": 1}


def test_laya_cpu_threads_reject_invalid_configuration(monkeypatch):
    import pytest

    fake_torch = SimpleNamespace(set_num_threads=lambda _value: None,
                                 set_num_interop_threads=lambda _value: None)
    monkeypatch.setenv("UMBRAL_LAYA_CPU_THREADS", "0")

    with pytest.raises(RuntimeError, match="entero entre 1 y 32"):
        _configure_cpu_threads(fake_torch)


def test_laya_load_uses_meta_build_and_assigns_checkpoint_storage(monkeypatch):
    fake_torch = SimpleNamespace(current_device="cpu")

    class DeviceContext:
        def __init__(self, device):
            self.device = device

        def __enter__(self):
            self.previous = fake_torch.current_device
            fake_torch.current_device = self.device

        def __exit__(self, *_args):
            fake_torch.current_device = self.previous

    class FakeModule:
        def __init__(self):
            self._buffers = {}

        def modules(self):
            return iter((self,))

        def load_state_dict(self, state_dict, strict=True, assign=False):
            self.strict = strict
            self.assign = assign
            if assign:
                self.storage = state_dict["weight"]
            return SimpleNamespace(missing_keys=[], unexpected_keys=[])

    fake_torch.device = DeviceContext
    fake_torch.nn = SimpleNamespace(Module=FakeModule)
    agent_module = ModuleType("fake_laya_agent")

    def build_model():
        model = FakeModule()
        model.build_device = fake_torch.current_device
        return model

    agent_module.build_model = build_model
    monkeypatch.setitem(sys.modules, agent_module.__name__, agent_module)
    fake_laya = SimpleNamespace(Agent=type("Agent", (), {"__module__": agent_module.__name__}))
    checkpoint_storage = object()
    created = {}

    def load_agent():
        model = agent_module.build_model()
        model.load_state_dict({"weight": checkpoint_storage}, strict=True)
        created["model"] = model
        return model

    loaded = _load_laya_agent(fake_laya, fake_torch, load_agent)

    assert loaded is created["model"]
    assert loaded.build_device == "meta"
    assert loaded.assign is True
    assert loaded.strict is True
    assert loaded.storage is checkpoint_storage
    assert fake_torch.current_device == "cpu"
    assert agent_module.build_model is build_model
    assert "assign" in inspect.signature(FakeModule.load_state_dict).parameters


def test_laya_load_recreates_only_uncheckpointed_rotary_buffers():
    from umbral_pipeline.classify.laya_clf import _restore_meta_rope_buffers

    class Tensor:
        def __init__(self, value, *, is_meta):
            self.value = value
            self.is_meta = is_meta

        def clone(self):
            return Tensor(self.value, is_meta=False)

    class Rotary:
        layer_types = ("full_attention",)
        rope_type = {"full_attention": "default"}
        config = object()

        def __init__(self):
            self._buffers = {
                "full_attention_inv_freq": Tensor(None, is_meta=True),
                "full_attention_original_inv_freq": Tensor(None, is_meta=True),
            }

        @staticmethod
        def compute_default_rope_parameters(config, *, device, layer_type):
            assert config is not None
            assert device.device == "cpu"
            assert layer_type == "full_attention"
            return Tensor("rotary-frequencies", is_meta=False), 1.0

    rotary = Rotary()
    model = SimpleNamespace(modules=lambda: iter((rotary,)))
    fake_torch = SimpleNamespace(device=lambda device: SimpleNamespace(device=device))

    _restore_meta_rope_buffers(model, fake_torch)

    assert rotary._buffers["full_attention_inv_freq"].value == "rotary-frequencies"
    assert rotary._buffers["full_attention_original_inv_freq"].value == "rotary-frequencies"
    assert not rotary._buffers["full_attention_inv_freq"].is_meta
    assert not rotary._buffers["full_attention_original_inv_freq"].is_meta
