"""
Specialized Agents - Role-specific agent implementations

Each agent has a specialized system prompt and capabilities
optimized for their role in the development process.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseAgent, AgentConfig
from ..lbm.coordinator import LBMCoordinator


class ArchitectAgent(BaseAgent):
    """
    Architect Agent - Designs system architecture and structure.

    Responsibilities:
    - Analyze requirements and define system architecture
    - Create project structure and module organization
    - Define interfaces and data models
    - Make technology decisions
    """

    @classmethod
    def create(
        cls,
        coordinator: LBMCoordinator,
        work_dir: Path,
        name: str = "Architect",
    ) -> "ArchitectAgent":
        """Create an architect agent with default config."""
        config = AgentConfig(
            name=name,
            role="architect",
            description="Designs system architecture and makes technology decisions",
            system_prompt="""You are an expert software architect. Your role is to:

1. **Analyze Requirements**: Break down project goals into technical requirements
2. **Design Architecture**: Create scalable, maintainable system designs
3. **Define Structure**: Organize code into logical modules and packages
4. **Choose Technologies**: Select appropriate frameworks, libraries, and tools
5. **Create Interfaces**: Define clear APIs and data contracts

## Best Practices
- Start with high-level design before implementation details
- Consider scalability, security, and maintainability
- Document key decisions with rationale
- Create clear separation of concerns
- Define interfaces before implementations

## Output Format
When sharing architectural decisions, include:
- Context: Why this decision was needed
- Decision: What was decided
- Consequences: What this means for the project
- Alternatives: What other options were considered""",
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        )
        return cls(config, coordinator, work_dir)

    async def execute_task(self, task: str) -> Dict[str, Any]:
        """Execute an architecture task."""
        results = []
        async for message in self.run(task):
            results.append(message)

            # Extract and share key decisions
            if message.get("type") == "assistant":
                for content in message.get("content", []):
                    if content.get("type") == "text":
                        text = content["text"]
                        # Look for decision patterns
                        if any(keyword in text.lower() for keyword in
                               ["decision:", "architecture:", "design:"]):
                            await self.share_insight(
                                text[:500],
                                claim_type="decision",
                                tags=["architecture"]
                            )

        return {"messages": results, "balance": self.get_balance()}


class DeveloperAgent(BaseAgent):
    """
    Developer Agent - Implements code and features.

    Responsibilities:
    - Write clean, tested code
    - Implement features according to architecture
    - Follow coding standards and best practices
    - Create unit tests for implementations
    """

    @classmethod
    def create(
        cls,
        coordinator: LBMCoordinator,
        work_dir: Path,
        name: str = "Developer",
        specialty: str = "full-stack",
    ) -> "DeveloperAgent":
        """Create a developer agent with optional specialty."""
        config = AgentConfig(
            name=name,
            role="developer",
            description=f"{specialty} developer implementing features and writing code",
            system_prompt=f"""You are an expert {specialty} developer. Your role is to:

1. **Implement Features**: Write clean, efficient code
2. **Follow Architecture**: Adhere to the defined system design
3. **Write Tests**: Create comprehensive unit and integration tests
4. **Handle Errors**: Implement proper error handling and logging
5. **Document Code**: Add clear docstrings and comments

## Best Practices
- Write self-documenting code with clear naming
- Keep functions small and focused
- Use type hints for better code quality
- Write tests alongside implementation
- Handle edge cases and errors gracefully

## Code Standards
- Follow PEP 8 for Python, ESLint for JavaScript
- Use async/await for I/O operations
- Implement proper logging
- Add input validation
- Use dependency injection where appropriate

## When Sharing Code
Tag implementations with:
- "implementation" for new features
- "bugfix" for bug fixes
- "refactor" for code improvements""",
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        )
        return cls(config, coordinator, work_dir)

    async def execute_task(self, task: str) -> Dict[str, Any]:
        """Execute a development task."""
        results = []
        async for message in self.run(task):
            results.append(message)

            # Share significant implementations
            if message.get("type") == "assistant":
                for content in message.get("content", []):
                    if content.get("type") == "tool_use":
                        tool = content.get("tool")
                        if tool in ["Write", "Edit"]:
                            # Share that we made code changes
                            input_data = content.get("input", {})
                            file_path = input_data.get("file_path", "unknown")
                            await self.share_insight(
                                f"Updated {file_path}",
                                claim_type="code",
                                tags=["implementation"]
                            )

        return {"messages": results, "balance": self.get_balance()}


class ReviewerAgent(BaseAgent):
    """
    Reviewer Agent - Reviews code and provides feedback.

    Responsibilities:
    - Review code for quality and security
    - Identify bugs and potential issues
    - Suggest improvements and optimizations
    - Ensure adherence to standards
    """

    @classmethod
    def create(
        cls,
        coordinator: LBMCoordinator,
        work_dir: Path,
        name: str = "Reviewer",
    ) -> "ReviewerAgent":
        """Create a reviewer agent with default config."""
        config = AgentConfig(
            name=name,
            role="reviewer",
            description="Reviews code for quality, security, and best practices",
            system_prompt="""You are an expert code reviewer. Your role is to:

1. **Review Quality**: Check code for clarity, efficiency, and maintainability
2. **Find Bugs**: Identify potential bugs, edge cases, and error conditions
3. **Security Audit**: Look for security vulnerabilities and risks
4. **Suggest Improvements**: Recommend optimizations and better patterns
5. **Verify Tests**: Ensure adequate test coverage

## Review Checklist
- [ ] Code follows project conventions
- [ ] Functions are well-named and documented
- [ ] Error handling is comprehensive
- [ ] No security vulnerabilities (SQL injection, XSS, etc.)
- [ ] Tests cover main functionality
- [ ] No hardcoded secrets or credentials
- [ ] Performance considerations addressed

## Review Format
For each finding, provide:
- **Severity**: Critical, High, Medium, Low
- **Location**: File and line number
- **Issue**: Description of the problem
- **Suggestion**: How to fix it

## When Sharing Reviews
Tag findings with:
- "security" for security issues
- "bug" for bugs
- "performance" for performance issues
- "style" for style/convention issues""",
            allowed_tools=["Read", "Glob", "Grep"],  # Reviewer shouldn't edit
        )
        return cls(config, coordinator, work_dir)

    async def execute_task(self, task: str) -> Dict[str, Any]:
        """Execute a review task."""
        results = []
        async for message in self.run(task):
            results.append(message)

            # Share review findings
            if message.get("type") == "assistant":
                for content in message.get("content", []):
                    if content.get("type") == "text":
                        text = content["text"]
                        # Look for review patterns
                        if any(keyword in text.lower() for keyword in
                               ["security", "bug", "issue", "recommend", "finding"]):
                            await self.share_insight(
                                text[:500],
                                claim_type="review",
                                tags=["code-review"]
                            )

        return {"messages": results, "balance": self.get_balance()}


class TesterAgent(BaseAgent):
    """
    Tester Agent - Creates and runs tests.

    Responsibilities:
    - Write comprehensive test suites
    - Run tests and report results
    - Identify test coverage gaps
    - Create test fixtures and mocks
    """

    @classmethod
    def create(
        cls,
        coordinator: LBMCoordinator,
        work_dir: Path,
        name: str = "Tester",
    ) -> "TesterAgent":
        """Create a tester agent with default config."""
        config = AgentConfig(
            name=name,
            role="tester",
            description="Creates comprehensive tests and ensures quality",
            system_prompt="""You are an expert QA engineer and test developer. Your role is to:

1. **Write Tests**: Create unit, integration, and end-to-end tests
2. **Run Tests**: Execute test suites and analyze results
3. **Find Gaps**: Identify areas lacking test coverage
4. **Create Fixtures**: Build test data and mock objects
5. **Report Issues**: Document test failures clearly

## Testing Best Practices
- Test behavior, not implementation
- Use descriptive test names
- One assertion concept per test
- Use fixtures for common setup
- Mock external dependencies

## Test Categories
- **Unit Tests**: Test individual functions/methods
- **Integration Tests**: Test component interactions
- **Edge Cases**: Test boundary conditions
- **Error Cases**: Test error handling paths

## When Sharing Test Results
Tag with:
- "test-pass" for passing suites
- "test-fail" for failures found
- "coverage" for coverage reports""",
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        )
        return cls(config, coordinator, work_dir)

    async def execute_task(self, task: str) -> Dict[str, Any]:
        """Execute a testing task."""
        results = []
        async for message in self.run(task):
            results.append(message)

            # Share test results
            if message.get("type") == "assistant":
                for content in message.get("content", []):
                    if content.get("type") == "tool_use":
                        tool = content.get("tool")
                        if tool == "Bash":
                            input_data = content.get("input", {})
                            command = input_data.get("command", "")
                            if "test" in command.lower() or "pytest" in command.lower():
                                await self.share_insight(
                                    f"Running tests: {command}",
                                    claim_type="test",
                                    tags=["testing"]
                                )

        return {"messages": results, "balance": self.get_balance()}


class DocumenterAgent(BaseAgent):
    """
    Documenter Agent - Creates documentation.

    Responsibilities:
    - Write README and getting started guides
    - Create API documentation
    - Document architecture and design
    - Write inline code documentation
    """

    @classmethod
    def create(
        cls,
        coordinator: LBMCoordinator,
        work_dir: Path,
        name: str = "Documenter",
    ) -> "DocumenterAgent":
        """Create a documenter agent with default config."""
        config = AgentConfig(
            name=name,
            role="documenter",
            description="Creates comprehensive documentation",
            system_prompt="""You are an expert technical writer. Your role is to:

1. **README**: Create clear project overview and setup instructions
2. **API Docs**: Document all public interfaces
3. **Architecture**: Explain system design and structure
4. **Tutorials**: Write getting started guides
5. **Comments**: Ensure code has clear documentation

## Documentation Standards
- Use clear, concise language
- Include code examples
- Keep docs up-to-date with code
- Use consistent formatting
- Add diagrams where helpful

## Documentation Types
- **README.md**: Project overview, installation, usage
- **API Reference**: Function signatures, parameters, returns
- **Architecture**: High-level design, component diagrams
- **Tutorials**: Step-by-step guides
- **CHANGELOG**: Version history

## When Sharing Documentation
Tag with:
- "readme" for README updates
- "api-docs" for API documentation
- "tutorial" for tutorials/guides""",
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        )
        return cls(config, coordinator, work_dir)

    async def execute_task(self, task: str) -> Dict[str, Any]:
        """Execute a documentation task."""
        results = []
        async for message in self.run(task):
            results.append(message)

            # Share documentation updates
            if message.get("type") == "assistant":
                for content in message.get("content", []):
                    if content.get("type") == "tool_use":
                        tool = content.get("tool")
                        if tool in ["Write", "Edit"]:
                            input_data = content.get("input", {})
                            file_path = input_data.get("file_path", "")
                            if file_path.endswith(".md"):
                                await self.share_insight(
                                    f"Updated documentation: {file_path}",
                                    claim_type="docs",
                                    tags=["documentation"]
                                )

        return {"messages": results, "balance": self.get_balance()}
