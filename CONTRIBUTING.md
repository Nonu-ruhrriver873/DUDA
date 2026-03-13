# Contributing to DUDA

Thank you for your interest in contributing to DUDA! This guide will help you get started.

## How to Contribute

### Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include your Claude Code version and OS
- For contamination detection issues, include (sanitized) project structure

### Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-improvement`
3. Make your changes
4. Run evals: ensure all test cases pass
5. Submit a Pull Request

### Pull Request Requirements

- [ ] All existing evals pass (weighted avg >= 98)
- [ ] New features include eval test cases
- [ ] English-only in user-facing content
- [ ] Python scripts use stdlib only (no pip dependencies)
- [ ] Code follows existing style conventions

## Development Setup

```bash
# Clone
git clone https://github.com/popup-studio-ai/duda-skill.git
cd duda-skill

# Install as Claude Code skill (for testing)
cp -r duda ~/.claude/skills/duda

# Run evals
# (Use Claude Code eval framework)
```

## Adding Eval Test Cases

Add new test cases to `evals/evals.json`:

```json
{
  "id": 17,
  "mode": "TRANSPLANT",
  "prompt": "Your test prompt here",
  "expected_output": "Expected behavior description",
  "expectations": [
    "Specific expectation 1",
    "Specific expectation 2"
  ]
}
```

Each expectation should be independently verifiable.

## Adding Isolation Patterns

Add new patterns to `references/patterns.md` following the format:

```markdown
### X-N. Pattern Name

**Risk Pattern:**
(code block with ❌ prefix comment)

**Fix Pattern:**
(code block with ✅ prefix comment)
```

## Code Style

- **Python**: PEP 8, type hints where helpful, docstrings for public functions
- **JavaScript**: ES6+, JSDoc for exported functions
- **Markdown**: ATX headings, fenced code blocks with language tags

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
