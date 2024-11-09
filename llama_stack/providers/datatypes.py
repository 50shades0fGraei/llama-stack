# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from enum import Enum
from typing import Any, List, Optional, Protocol
from urllib.parse import urlparse

from llama_models.schema_utils import json_schema_type
from pydantic import BaseModel, Field

from llama_stack.apis.datasets import DatasetDef
from llama_stack.apis.eval_tasks import EvalTaskDef
from llama_stack.apis.memory_banks.memory_banks import MemoryBank
from llama_stack.apis.models import Model
from llama_stack.apis.scoring_functions import ScoringFnDef
from llama_stack.apis.shields import Shield


@json_schema_type
class Api(Enum):
    inference = "inference"
    safety = "safety"
    agents = "agents"
    memory = "memory"
    datasetio = "datasetio"
    scoring = "scoring"
    eval = "eval"

    telemetry = "telemetry"

    models = "models"
    shields = "shields"
    memory_banks = "memory_banks"
    datasets = "datasets"
    scoring_functions = "scoring_functions"
    eval_tasks = "eval_tasks"

    # built-in API
    inspect = "inspect"


class ModelsProtocolPrivate(Protocol):
    async def register_model(self, model: Model) -> None: ...


class ShieldsProtocolPrivate(Protocol):
    async def register_shield(self, shield: Shield) -> None: ...


class MemoryBanksProtocolPrivate(Protocol):
    async def list_memory_banks(self) -> List[MemoryBank]: ...

    async def register_memory_bank(self, memory_bank: MemoryBank) -> None: ...


class DatasetsProtocolPrivate(Protocol):
    async def list_datasets(self) -> List[DatasetDef]: ...

    async def register_dataset(self, dataset_def: DatasetDef) -> None: ...


class ScoringFunctionsProtocolPrivate(Protocol):
    async def list_scoring_functions(self) -> List[ScoringFnDef]: ...

    async def register_scoring_function(self, function_def: ScoringFnDef) -> None: ...


class EvalTasksProtocolPrivate(Protocol):
    async def list_eval_tasks(self) -> List[EvalTaskDef]: ...

    async def register_eval_task(self, eval_task_def: EvalTaskDef) -> None: ...


@json_schema_type
class ProviderSpec(BaseModel):
    api: Api
    provider_type: str
    config_class: str = Field(
        ...,
        description="Fully-qualified classname of the config for this provider",
    )
    api_dependencies: List[Api] = Field(
        default_factory=list,
        description="Higher-level API surfaces may depend on other providers to provide their functionality",
    )
    deprecation_warning: Optional[str] = Field(
        default=None,
        description="If this provider is deprecated, specify the warning message here",
    )

    # used internally by the resolver; this is a hack for now
    deps__: List[str] = Field(default_factory=list)


class RoutingTable(Protocol):
    def get_provider_impl(self, routing_key: str) -> Any: ...


@json_schema_type
class AdapterSpec(BaseModel):
    adapter_type: str = Field(
        ...,
        description="Unique identifier for this adapter",
    )
    module: str = Field(
        ...,
        description="""
Fully-qualified name of the module to import. The module is expected to have:

 - `get_adapter_impl(config, deps)`: returns the adapter implementation
""",
    )
    pip_packages: List[str] = Field(
        default_factory=list,
        description="The pip dependencies needed for this implementation",
    )
    config_class: Optional[str] = Field(
        default=None,
        description="Fully-qualified classname of the config for this provider",
    )
    provider_data_validator: Optional[str] = Field(
        default=None,
    )


@json_schema_type
class InlineProviderSpec(ProviderSpec):
    pip_packages: List[str] = Field(
        default_factory=list,
        description="The pip dependencies needed for this implementation",
    )
    docker_image: Optional[str] = Field(
        default=None,
        description="""
The docker image to use for this implementation. If one is provided, pip_packages will be ignored.
If a provider depends on other providers, the dependencies MUST NOT specify a docker image.
""",
    )
    module: str = Field(
        ...,
        description="""
Fully-qualified name of the module to import. The module is expected to have:

 - `get_provider_impl(config, deps)`: returns the local implementation
""",
    )
    provider_data_validator: Optional[str] = Field(
        default=None,
    )


class RemoteProviderConfig(BaseModel):
    host: str = "localhost"
    port: Optional[int] = None
    protocol: str = "http"

    @property
    def url(self) -> str:
        if self.port is None:
            return f"{self.protocol}://{self.host}"
        return f"{self.protocol}://{self.host}:{self.port}"

    @classmethod
    def from_url(cls, url: str) -> "RemoteProviderConfig":
        parsed = urlparse(url)
        return cls(host=parsed.hostname, port=parsed.port, protocol=parsed.scheme)


@json_schema_type
class RemoteProviderSpec(ProviderSpec):
    adapter: Optional[AdapterSpec] = Field(
        default=None,
        description="""
If some code is needed to convert the remote responses into Llama Stack compatible
API responses, specify the adapter here. If not specified, it indicates the remote
as being "Llama Stack compatible"
""",
    )

    @property
    def docker_image(self) -> Optional[str]:
        return None

    @property
    def module(self) -> str:
        if self.adapter:
            return self.adapter.module
        return "llama_stack.distribution.client"

    @property
    def pip_packages(self) -> List[str]:
        if self.adapter:
            return self.adapter.pip_packages
        return []

    @property
    def provider_data_validator(self) -> Optional[str]:
        if self.adapter:
            return self.adapter.provider_data_validator
        return None


def is_passthrough(spec: ProviderSpec) -> bool:
    return isinstance(spec, RemoteProviderSpec) and spec.adapter is None


# Can avoid this by using Pydantic computed_field
def remote_provider_spec(
    api: Api, adapter: Optional[AdapterSpec] = None
) -> RemoteProviderSpec:
    config_class = (
        adapter.config_class
        if adapter and adapter.config_class
        else "llama_stack.distribution.datatypes.RemoteProviderConfig"
    )
    provider_type = f"remote::{adapter.adapter_type}" if adapter else "remote"

    return RemoteProviderSpec(
        api=api, provider_type=provider_type, config_class=config_class, adapter=adapter
    )
