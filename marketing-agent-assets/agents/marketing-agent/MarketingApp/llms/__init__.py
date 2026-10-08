"""
LLMs Katmanı — BaseModel ve SubModel'leri dışa aktarır.
Boot sırasında tüm SubModel'leri otomatik olarak yükler ve registry'ye kaydeder.
"""

from .BaseModel import BaseModel
from .SubModels import SubModel, get_submodel, list_submodels, register_submodel, get_all_submodels

# Boot: SubModel modullerini import ederek auto-register et.
from .SubModels import browser_agent  # noqa: F401
from .SubModels import content_creator_agent  # noqa: F401
from .SubModels import sosyal_medya_agent  # noqa: F401

__all__ = [
    "BaseModel",
    "SubModel",
    "get_submodel",
    "get_all_submodels",
    "list_submodels",
    "register_submodel",
]
