# Security Policy

## Supported Versions

Security updates and patches are actively maintained for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of hotel guests, merchant transaction data, and hospitality operations seriously.

If you believe you have discovered a security vulnerability in FolioShield, please report it privately:

- **Do NOT** open a public GitHub issue for security vulnerabilities.
- Please email our security team at **security@folioshield.io** (or your designated security contact) with:
  - Description of the vulnerability
  - Clear steps to reproduce or proof-of-concept
  - Potential impact assessment
- You will receive an acknowledgment within 48 hours.
- We will coordinate with you on responsible disclosure and timeline before public release.

## Security Practices in FolioShield

FolioShield enforces strict defense-in-depth principles:
- **PCI-DSS Compliance / PAN Redaction:** Primary Account Numbers (credit card numbers) are masked at ingestion time. Only the last 4 digits are ever retained or displayed.
- **Fail-Closed API Authentication:** In production, legacy unauthenticated access is disabled by default. All requests require valid API keys or Bearer integration credentials.
- **Tamper-Evident Evidence Store:** All uploaded documents are verified with SHA-256 content hashes, and audit trails use cryptographic hash-chaining to detect retroactive alterations.
- **Encrypted Secrets:** Webhook signing secrets and API credentials are encrypted at rest.
