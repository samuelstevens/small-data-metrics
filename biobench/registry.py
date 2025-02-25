"""
Stores all vision backbones.
Users can register new custom backbones from their code to evaluate on biobench using `register_vision_backbone`.
As long as it satisfies the `biobench.interfaces.VisionBackbone` interface, it will work will all tasks.

.. include:: ./tutorial.md
"""

import logging

import beartype

from . import interfaces

logger = logging.getLogger(__name__)

_global_backbone_registry: dict[str, type[interfaces.VisionBackbone]] = {}


@beartype.beartype
def load_vision_backbone(
    model_args: interfaces.ModelArgsCvml,
) -> interfaces.VisionBackbone:
    """
    Load a pretrained vision backbone.
    """
    if model_args.org not in _global_backbone_registry:
        raise ValueError(f"Org '{model_args.org}' not found.")

    cls = _global_backbone_registry[model_args.org]
    return cls(model_args.ckpt)


def register_vision_backbone(model_org: str, cls: type[interfaces.VisionBackbone]):
    """
    Register a new vision backbone class.
    """
    if model_org in _global_backbone_registry:
        logger.warning("Overwriting key '%s' in registry.", model_org)
    _global_backbone_registry[model_org] = cls


def list_vision_backbones() -> list[str]:
    """
    List all vision backbone model orgs.
    """
    return list(_global_backbone_registry.keys())


_global_mllm_registry: dict[str, interfaces.MultimodalLlm] = {}


@beartype.beartype
def load_mllm(
    model_args: interfaces.ModelArgsMllm,
) -> interfaces.MultimodalLlm:
    """
    Load a multimodal LLM configuration.
    """
    if model_args.ckpt not in _global_mllm_registry:
        raise ValueError(f"Model '{model_args.ckpt}' not found.")

    return _global_mllm_registry[model_args.ckpt]


def register_mllm(model_name: str, mllm: interfaces.MultimodalLlm):
    """
    Register a new multimodal LLM configuration.
    """
    if model_name in _global_mllm_registry:
        logger.warning("Overwriting key '%s' in registry.", model_name)
    _global_mllm_registry[model_name] = mllm


def list_mllms() -> list[str]:
    """
    List all registered multimodal LLM models.
    """
    return list(_global_mllm_registry.keys())
