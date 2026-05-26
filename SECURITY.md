# Security Policy

## Threat Model

MAGI is a single-user CLI tool that communicates with a local Ollama instance. The primary trust boundaries are:

1. **User input → LLM prompts**: The user is the sole input source. Prompt injection is a non-issue because the user can only attack themselves.
2. **Ollama responses → terminal output**: A compromised Ollama server could return malicious payloads. MAGI sanitizes all LLM output (ANSI escape stripping, control character removal, response size caps) before rendering.
3. **Filesystem**: Journal and config files are written to `~/.config/magi/` with restrictive permissions (0o700 dir, 0o600 files). Symlink attacks are detected and rejected.

## Security Measures

- OLLAMA_HOST validated (scheme, non-localhost warning)
- All LLM output sanitized for terminal escape injection
- HTTP response size capped at 1MB
- Content-Type validation on all HTTP responses
- User input capped at 10,000 characters
- Journal writes are atomic (tempfile + rename)
- Symlink detection on all file paths
- File permissions enforced and auto-repaired on access
- Exception messages sanitized to prevent hostname/URL leakage
- No shell execution, eval, exec, or pickle anywhere in the codebase

## Supported Versions

Only the latest release receives security updates.

## Reporting a Vulnerability

If you discover a security issue:

1. **Do NOT open a public GitHub issue.**
2. Email: dev@0arch.io
3. Include: description, steps to reproduce, impact assessment.
4. You will receive acknowledgment within 48 hours.
5. We aim to issue a fix within 7 days for critical issues.

## Scope

In-scope:
- Terminal injection via crafted LLM responses
- File permission escalation
- SSRF via OLLAMA_HOST manipulation
- Information disclosure through error messages
- Denial of service (OOM, infinite loops)

Out-of-scope:
- Prompt injection (user attacking themselves)
- Attacks requiring physical access to the machine
- Social engineering
- Ollama's own security (report to Ollama directly)
