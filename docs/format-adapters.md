# Format adapters

Worklog normalizes each source into `Conversation` and `Message` objects. Adapters are intentionally small and can be extended without changing report generation.

## Codex

The first adapter accepts JSON or JSONL files whose name or payload identifies Codex/OpenAI. It understands `messages`, `conversation.messages`, and JSONL records. Message content can be a string, `parts`, or text blocks.

## Claude

The Claude adapter accepts JSON or JSONL files whose name or payload identifies Claude/Anthropic. It understands `messages` and `chat_messages`, including `sender`, `created_at`, and block-based `content`.

## Markdown

For small hand-curated exports, a file can use this shape:

```markdown
# Conversation title

## user
项目: docs

## assistant
已完成本周的文档整理。
```

Provider identity for Markdown is inferred from the filename (`codex`, `openai`, `claude`, or `anthropic`). Unsupported files are reported without changing the database.
