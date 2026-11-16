"""Off-the-shelf model attribution baseline for 2c: Sun et al.'s chat API classifier in 4-bit.

See model/sun_classifier/README.md. Heavy dependencies (torch, transformers, bitsandbytes) are
imported only inside the functions that need them, so the rest of model/ and CI work without them.
"""

# Label order of Yida/classifier_chat: the order of --response_paths in Sun et al.'s README.
LABELS = ["ChatGPT", "Claude", "Grok", "Gemini", "DeepSeek"]

# Provider behind each label, in the project's provider names, and the exact model each label was
# trained on (generate_responses.py in locuslab/llm-idiosyncrasies).
PROVIDERS = {
    "ChatGPT": "openai",
    "Claude": "anthropic",
    "Grok": "xai",
    "Gemini": "google",
    "DeepSeek": "deepseek",
}
TRAINED_ON = {
    "ChatGPT": "gpt-4o-2024-08-06",
    "Claude": "claude-3-5-sonnet-20241022",
    "Grok": "grok-beta",
    "Gemini": "gemini-1.5-pro-002",
    "DeepSeek": "deepseek-chat",
}
