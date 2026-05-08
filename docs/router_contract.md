# Router Contract

This document defines the first routing decision interface for `sfe`.

The router receives a user task and returns a routing decision. It does not execute the task, retrieve memory, call providers, or update memory. Its responsibility is to describe how the rest of the system should bound context and select execution.

## Routing Decision Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SFERoutingDecision",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "task_type",
    "role",
    "provider",
    "model",
    "memory_zones",
    "execution_mode",
    "max_input_tokens",
    "max_output_tokens",
    "requires_review",
    "confidence",
    "rationale"
  ],
  "properties": {
    "task_type": {
      "type": "string",
      "enum": ["writing", "coding", "review", "analysis", "planning", "multi_context"],
      "description": "Coarse classification of the user task."
    },
    "role": {
      "type": "string",
      "enum": ["writer", "executor", "architect", "reviewer"],
      "description": "Primary processing role for the task."
    },
    "provider": {
      "type": "string",
      "description": "Execution provider selected for the task."
    },
    "model": {
      "type": "string",
      "description": "Model identifier selected for execution."
    },
    "memory_zones": {
      "type": "array",
      "description": "Ordered list of spatial memory zones to activate for this task.",
      "items": {
        "type": "string"
      },
      "uniqueItems": true
    },
    "execution_mode": {
      "type": "string",
      "enum": ["direct", "tool_assisted", "multi_step"],
      "description": "How the task should be executed."
    },
    "max_input_tokens": {
      "type": "integer",
      "minimum": 1,
      "description": "Maximum input/context budget for the execution step."
    },
    "max_output_tokens": {
      "type": "integer",
      "minimum": 1,
      "description": "Maximum output budget for the execution step."
    },
    "requires_review": {
      "type": "boolean",
      "description": "Whether the result should pass through a review role before completion."
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "multipleOf": 0.01,
      "description": "Router confidence in this decision."
    },
    "rationale": {
      "type": "string",
      "description": "Short explanation of why this route was selected."
    }
  }
}
```

## Field Definitions

- `task_type`: A coarse task label such as `writing`, `coding`, `review`, `analysis`, `planning`, or `multi_context`.
- `role`: The primary role that should process the task, such as `writer`, `executor`, `architect`, or `reviewer`.
- `provider`: The provider namespace to use, such as `local`, `openai`, or another configured provider.
- `model`: The provider-specific model identifier.
- `memory_zones`: The bounded set of memory zones to activate for this task. An empty array is valid when no prior memory is needed.
- `execution_mode`: The execution pattern, such as `direct`, `tool_assisted`, or `multi_step`.
- `max_input_tokens`: The maximum context budget made available to the selected role and model.
- `max_output_tokens`: The maximum generation budget for the selected role and model.
- `requires_review`: Whether an optional review step should run after execution.
- `confidence`: A normalized score from `0` to `1`.
- `rationale`: A concise, human-readable explanation for traceability.

## Examples

### Writing Task

```json
{
  "task_type": "writing",
  "role": "writer",
  "provider": "openai",
  "model": "provider-model-id",
  "memory_zones": ["project_overview", "style_constraints"],
  "execution_mode": "direct",
  "max_input_tokens": 8000,
  "max_output_tokens": 2000,
  "requires_review": true,
  "confidence": 0.86,
  "rationale": "The user is asking for prose generation, so the writer role should run with project and style context."
}
```

### Coding Task

```json
{
  "task_type": "coding",
  "role": "executor",
  "provider": "openai",
  "model": "provider-model-id",
  "memory_zones": ["project_overview", "codebase_context", "technical_constraints"],
  "execution_mode": "tool_assisted",
  "max_input_tokens": 12000,
  "max_output_tokens": 3000,
  "requires_review": true,
  "confidence": 0.9,
  "rationale": "The user is requesting code changes, so execution needs codebase context, tools, and a review pass."
}
```

### Multi-Context Task

```json
{
  "task_type": "multi_context",
  "role": "architect",
  "provider": "openai",
  "model": "provider-model-id",
  "memory_zones": ["project_overview", "technical_knowledge", "decisions", "user_preferences"],
  "execution_mode": "multi_step",
  "max_input_tokens": 16000,
  "max_output_tokens": 4000,
  "requires_review": true,
  "confidence": 0.78,
  "rationale": "The task spans project goals, technical tradeoffs, prior decisions, and user preferences, so an architect role should coordinate a bounded multi-step response."
}
```
