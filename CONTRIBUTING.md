# Contributing to FolioShield

Thank you for your interest in contributing to FolioShield! We welcome contributions to improve hotel chargeback defense, document parsing accuracy, audit durability, and integration support.

## Code of Conduct

Please maintain a respectful, welcoming, and collaborative environment. Be thoughtful, honest, and constructive in all code reviews, discussions, and issues.

## Development Workflow

### 1. Prerequisites
- Python 3.11 or 3.12
- Git

### 2. Setup Local Environment

```bash
# Clone the repository
git clone https://github.com/your-org/FolioShield.git
cd FolioShield

# Create and activate virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Running the Test Suite

Always verify tests before committing or opening a PR:

```bash
python -m unittest discover -s tests -v
```

### 4. Running the Local Application

```bash
streamlit run app.py
```

### 5. Architectural Standards

When contributing, ensure you adhere to our core architectural principles:
- **Outside-in, document-first:** Never assume direct PMS access; extract deterministically from real files first.
- **Fail-safe, honest reporting:** Never invent, mock, or fake human approvals or evidence. If an exhibit or field is missing or unverified, honestly report it as unverified.
- **Durable persistence:** Cases, evidence checksums, and audit logs must persist safely across server restarts.
- **Card-network rules compliance:** Ensure reason codes, compelling evidence requirements, and rebuttal chronologies follow official card brand rules (Visa, Mastercard, Amex, Discover).
- **Test coverage:** Any new parser, validator, or integration feature must include corresponding automated unit/integration tests in the `tests/` directory.

## Submitting Pull Requests

1. Fork the repo and create your branch from `main` or `develop` (`git checkout -b feature/my-new-feature`).
2. Commit your changes with clear, descriptive commit messages.
3. Ensure all tests pass (`python -m unittest discover -s tests`).
4. Push to your fork and submit a Pull Request with a clear description of the problem solved and test evidence.
