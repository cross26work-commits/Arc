from app.code_generation.contract import (
    CODE_GENERATION_CONTRACT_VERSION,
    CodeGenerationContract,
    CodeGenerationContractError,
    CodeGenerationEdit,
    validate_code_generation_contract,
    validate_code_generation_contract_safe,
)
from app.code_generation.context_validator import (
    CONTEXT_VALIDATOR_VERSION,
    CodeGenerationContextValidationError,
    validate_contract_against_context,
    validate_contract_against_context_safe,
    validate_payload_against_context,
)
from app.code_generation.patch_converter import (
    DEFAULT_GENERATED_BY,
    PATCH_REQUEST_CONVERTER_VERSION,
    CodeGenerationPatchConversionError,
    build_patch_generate_request,
    convert_contract_to_patch_request,
    convert_contract_to_patch_request_safe,
)
from app.code_generation.patch_integration import (
    PATCH_INTEGRATION_VERSION,
    CodeGenerationPatchIntegrationError,
    run_code_generation_patch_integration,
    run_code_generation_patch_integration_safe,
)

__all__ = [
    "CODE_GENERATION_CONTRACT_VERSION",
    "CONTEXT_VALIDATOR_VERSION",
    "DEFAULT_GENERATED_BY",
    "PATCH_REQUEST_CONVERTER_VERSION",
    "CodeGenerationContract",
    "CodeGenerationContractError",
    "CodeGenerationContextValidationError",
    "CodeGenerationEdit",
    "CodeGenerationPatchConversionError",
    "build_patch_generate_request",
    "convert_contract_to_patch_request",
    "convert_contract_to_patch_request_safe",
    "validate_code_generation_contract",
    "validate_code_generation_contract_safe",
    "validate_contract_against_context",
    "validate_contract_against_context_safe",
    "validate_payload_against_context",
    "PATCH_INTEGRATION_VERSION",
    "CodeGenerationPatchIntegrationError",
    "run_code_generation_patch_integration",
    "run_code_generation_patch_integration_safe",
]

from .llm_adapter import (
    LLM_ADAPTER_VERSION,
    CodeGenerationLLMAdapter,
    CodeGenerationLLMAdapterError,
    DeterministicCodeGenerationLLMAdapter,
    LLMGenerationRequest,
    LLMGenerationResponse,
    calculate_generation_input_sha256,
    calculate_generation_response_sha256,
    extract_json_object,
)

from .llm_pipeline import (
    LLM_PIPELINE_VERSION,
    CodeGenerationLLMPipelineError,
    run_code_generation_llm_pipeline,
    run_code_generation_llm_pipeline_safe,
)

from .ollama_adapter import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_ADAPTER_VERSION,
    OllamaAdapterConfig,
    OllamaCodeGenerationLLMAdapter,
    OllamaCodeGenerationLLMAdapterError,
    OllamaConnectionError,
    OllamaHTTPError,
    OllamaResponseError,
    OllamaTimeoutError,
)
