"""Gemini LLM client wrapper."""

import os
from enum import Enum
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()


class PromptMode(Enum):
    EXTRACTION = "extraction"
    INFERENCE = "inference"
    DOCUMENTATION = "documentation"
    VALIDATION = "validation"


class GeminiClient:
    """Central gateway for Gemini LLM interactions."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set")

        model_name = model or os.getenv("LLM_MODEL", "").strip() or "gemini-2.5-flash"

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model_name)
        self.model_name = model_name
        self._validate_connection()

    def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        mode: PromptMode = PromptMode.EXTRACTION,
    ) -> str:
        """Generate response from Gemini with structured prompts."""

        system_prompts = {
            PromptMode.EXTRACTION: (
                "You are a code analysis expert. Extract structured information "
                "from the provided code and manifests. Be precise and factual."
            ),
            PromptMode.INFERENCE: (
                "You are a system architecture expert. Infer logical relationships "
                "and system structure from the provided information."
            ),
            PromptMode.DOCUMENTATION: (
                "You are a technical documentation expert. Generate clear, "
                "comprehensive documentation from the provided structured data."
            ),
            PromptMode.VALIDATION: (
                "You are a validation expert. Check for consistency, completeness, "
                "and accuracy in the provided information."
            ),
        }

        full_prompt = f"{system_prompts[mode]}\n\n"

        if context:
            full_prompt += "Context:\n"
            for key, value in context.items():
                full_prompt += f"{key}: {value}\n"
            full_prompt += "\n"

        full_prompt += f"Task: {prompt}"

        try:
            response = self.model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            return f"Error generating response: {str(e)}"

    def extract_entities(
        self, code_snippet: str, manifest: Optional[str] = None
    ) -> str:
        """Extract entities from code and manifests."""
        context = {"code": code_snippet}
        if manifest:
            context["manifest"] = manifest

        prompt = (
            "Extract key entities such as services, APIs, dependencies, "
            "and configurations. Return as structured data."
        )
        return self.generate(prompt, context, PromptMode.EXTRACTION)

    def infer_relationships(self, graph_excerpt: Dict[str, Any]) -> str:
        """Infer relationships between entities."""
        prompt = (
            "Based on the provided graph data, infer logical relationships "
            "between services, APIs, and deployments."
        )
        return self.generate(prompt, {"graph": str(graph_excerpt)}, PromptMode.INFERENCE)

    def generate_documentation(
        self, doc_type: str, graph_data: Dict[str, Any]
    ) -> str:
        """Generate documentation from graph data."""
        prompt = f"Generate {doc_type} documentation from the provided graph data."
        return self.generate(
            prompt, {"graph": str(graph_data)}, PromptMode.DOCUMENTATION
        )

    def validate_content(self, generated_content: str, source_data: str) -> str:
        """Validate generated content against source data."""
        prompt = (
            "Validate that the generated content accurately reflects "
            "the source data without hallucinations."
        )
        context = {"generated": generated_content, "source": source_data}
        return self.generate(prompt, context, PromptMode.VALIDATION)

    def _validate_connection(self) -> None:
        """Validate API connection on initialization."""
        try:
            response = self.model.generate_content("Test connection. Reply with 'OK'.")
            if response and response.text:
                pass
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Gemini API: {str(e)}")
