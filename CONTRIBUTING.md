# Contributing

Thank you for your interest in contributing to this project!

## Getting Started

1. Fork the repository and create a feature branch
2. Make your changes following existing code patterns
3. Test your changes
4. Submit a pull request with a clear description

## What to Contribute

- Bug fixes and improvements
- Documentation updates
- Test coverage improvements
- Performance optimizations

## Guidelines

- Follow the existing code style
- Include tests for new functionality when applicable
- Update documentation if needed
- Keep changes focused and atomic

## Development Setup

For detailed development instructions, testing guidelines, and code quality standards, see [DEVELOPMENT.md](./DEVELOPMENT.md).

## PR coverage requirements

Bug-fix PRs must declare a bug class (A-M) from `.claude/commands/mcp-functional-testing.bug-classes.yaml` in the PR body. PRs adding new MCP tools, actions, or endpoints must update `.claude/commands/mcp-test-coverage-matrix.yaml`. The PR template prompts for both; the `pr-coverage-check` CI workflow verifies them. See `docs/mcp-test-skill-improvement-plan.md` section 8.1.

## Questions?

- Check existing issues first
- For bugs: Create an issue with reproduction steps
- For questions: Email support@revenium.io

## Security

For security vulnerabilities, please follow our [Security Policy](https://github.com/revenium/revenium-mcp/blob/HEAD/SECURITY.md) - do not create public issues.

## License

By contributing, you agree your contributions will be licensed under the same license as this project.