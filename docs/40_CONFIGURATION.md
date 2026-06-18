# Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

`.env` is ignored by Git. Do not commit keys or local provider tokens.

## Shared Provider

Set one provider for all roles:

```env
SFE_PROVIDER=openai
OPENAI_API_KEY=...
```

Supported provider values include:

- `openai`
- `anthropic`
- `google`
- `alibaba`
- `codexcli`
- `lemonade`
- `ollama`

Provider-specific variables are listed in `.env.example`.

## Role Split

You can route, discover, and execute with different providers:

```env
SFE_PROVIDER_ROUTER=openai
SFE_PROVIDER_DISCOVERY=openai
SFE_PROVIDER_EXECUTOR=anthropic
```

Blank role variables fall back to the shared provider.

## Aider Writer

Normal `workspace_write` runs use Aider by default:

```env
SFE_WORKSPACE_WRITE_EXECUTOR=aider
```

Leave the variable unset for the default. Aider cannot use CodexCLI as its LLM
backend. If `SFE_PROVIDER=codexcli`, set `SFE_AIDER_PROVIDER` to an
Aider-compatible provider such as `openai`, `anthropic`, `google`, `alibaba`,
`lemonade`, or `ollama`.

`SFE_AIDER_MODEL` is the explicit model override passed to Aider/LiteLLM. Set it
when your SFE executor model name is not already a valid Aider/LiteLLM model
name. For Lemonade, the model may need the OpenAI-compatible prefix:

```env
SFE_AIDER_PROVIDER=lemonade
SFE_AIDER_MODEL=openai/Gemma-4-E4B-it-GGUF
```

The legacy text transport remains available for rollback or debugging:

```env
SFE_WORKSPACE_WRITE_EXECUTOR=text
```

Do not use the legacy text transport as the normal public path.

## Multi-Pass And Verification

Large write tasks can use multi-pass mode:

```env
SFE_WORKSPACE_WRITE_MULTIPASS=auto
SFE_MULTIPASS_MAX_PASSES=auto
```

Completed write attempts can be checked by a bounded verifier loop:

```env
SFE_REAL_LOOP=auto
SFE_REAL_LOOP_MAX_ITERATIONS=3
```

`SFE_REAL_LOOP_MAX_ITERATIONS` counts the original write attempt plus retries.
