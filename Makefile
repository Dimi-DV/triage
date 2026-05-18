.PHONY: help install lint format typecheck test test-cov check run-mcp-server eval eval-scenario plan apply destroy clean fis-list build-mcp-image push-mcp-image build-agent-image push-agent-image redeploy-mcp provision-agentcore provision-agentcore-dry agent-smoke

# Default target: show help
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Triage — common commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ============================================================
# Python development
# ============================================================

install: ## Install all deps (incl. dev) via uv
	uv sync --all-extras
	uv run pre-commit install

lint: ## Run ruff linter
	uv run ruff check .

format: ## Auto-format code with ruff
	uv run ruff format .

typecheck: ## Run mypy strict type checker on src/
	uv run mypy src/

test: ## Run pytest (unit + integration)
	uv run pytest

test-unit: ## Run only unit tests
	uv run pytest -m unit

test-cov: ## Run pytest with coverage report (HTML + terminal)
	uv run pytest --cov=src --cov-report=html --cov-report=term

check: lint format typecheck test ## Run all quality gates (CI mirror)

run-mcp-server: ## Run the MCP server locally (stdio transport)
	uv run python -m triage.mcp_server

# ============================================================
# Container images (Day 34 afternoon)
# ============================================================

# Read repo URLs lazily so missing Terraform state doesn't break `make help`.
AWS_REGION ?= us-east-1
ECR_REGISTRY = $(shell terraform -chdir=terraform/stack output -raw mcp_server_repository_url 2>/dev/null | cut -d/ -f1)
MCP_REPO_URL = $(shell terraform -chdir=terraform/stack output -raw mcp_server_repository_url 2>/dev/null)
AGENT_REPO_URL = $(shell terraform -chdir=terraform/stack output -raw agent_repository_url 2>/dev/null)
MCP_SERVICE_NAME = $(shell terraform -chdir=terraform/stack output -raw mcp_server_service_name 2>/dev/null)
ECS_CLUSTER_NAME = $(shell terraform -chdir=terraform/stack output -raw ecs_cluster_name 2>/dev/null)

ecr-login: ## Authenticate Docker to the project's ECR registry
	@test -n "$(ECR_REGISTRY)" || (echo "ECR registry unknown — terraform apply first"; exit 1)
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)

build-mcp-image: ## Build the MCP server container image
	docker build -f src/triage/mcp_server/Dockerfile -t triage-mcp-server:latest .

push-mcp-image: ecr-login build-mcp-image ## Build + push the MCP server image to ECR
	docker tag triage-mcp-server:latest $(MCP_REPO_URL):latest
	docker push $(MCP_REPO_URL):latest

build-agent-image: ## Build the agent runtime container image (arm64 — AgentCore Runtime requires arm64)
	docker build -f src/triage/agent/Dockerfile -t triage-agent:latest .

push-agent-image: ecr-login build-agent-image ## Build + push the agent image to ECR
	docker tag triage-agent:latest $(AGENT_REPO_URL):latest
	docker push $(AGENT_REPO_URL):latest

redeploy-mcp: ## Force ECS to redeploy the MCP service after a new image push
	aws ecs update-service \
	  --cluster $(ECS_CLUSTER_NAME) \
	  --service $(MCP_SERVICE_NAME) \
	  --force-new-deployment \
	  --no-cli-pager

# ============================================================
# AgentCore provisioning (Day 34 evening)
# ============================================================

provision-agentcore: ## Create / update AgentCore Runtime + Gateway + Identity + Cedar bindings
	uv run python scripts/provision_agentcore.py

provision-agentcore-dry: ## Show what provision_agentcore would do
	uv run python scripts/provision_agentcore.py --dry-run

agent-smoke: ## End-to-end smoke: invoke AgentCore Runtime with a synthetic alarm
	uv run python scripts/smoke_agent.py

# ============================================================
# Evaluation
# ============================================================

eval: ## Run full AgentCore Evaluations corpus against the deployed agent
	@echo "TODO Day 35: wire up to AgentCore Evaluations API"
	@echo "  Expected: aws bedrock-agentcore-control start-evaluation --evaluation-set-name triage-corpus"

eval-scenario: ## Run a single eval scenario (usage: make eval-scenario SCENARIO=az-slowdown)
	@if [ -z "$(SCENARIO)" ]; then echo "Usage: make eval-scenario SCENARIO=<name>"; exit 1; fi
	@echo "TODO Day 35: run scenario $(SCENARIO)"

# ============================================================
# Infrastructure (Terraform)
# ============================================================

plan: ## terraform plan against the production stack
	cd terraform/stack && terraform plan -out=tfplan

apply: ## terraform apply (requires fresh plan; hook-gated)
	cd terraform/stack && terraform apply tfplan

destroy: ## terraform destroy the production stack (asks for confirmation)
	cd terraform/stack && terraform destroy

tf-init: ## terraform init for the stack
	cd terraform/stack && terraform init

tf-fmt: ## Format all Terraform files
	terraform fmt -recursive terraform/

tf-validate: ## Validate Terraform syntax (no AWS access required)
	cd terraform/stack && terraform init -backend=false && terraform validate

# ============================================================
# Fault Injection Service
# ============================================================

fis-list: ## List available FIS experiment templates
	aws fis list-experiment-templates --query 'experimentTemplates[].{Id:id,Name:tags.Name}' --output table

fis-run: ## Start an FIS experiment (usage: make fis-run TEMPLATE=<id>)
	@if [ -z "$(TEMPLATE)" ]; then echo "Usage: make fis-run TEMPLATE=<experiment-template-id>"; exit 1; fi
	aws fis start-experiment --experiment-template-id $(TEMPLATE)

# ============================================================
# Housekeeping
# ============================================================

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".last-tf-plan" -delete 2>/dev/null || true

journal: ## Create today's journal entry (docs/journal/YYYY-MM-DD.md)
	@DATE=$$(date +%Y-%m-%d); \
	FILE=docs/journal/$$DATE.md; \
	if [ -f "$$FILE" ]; then echo "Journal already exists: $$FILE"; else \
	echo "# $$DATE" > $$FILE; \
	echo "" >> $$FILE; \
	echo "## Built" >> $$FILE; echo "" >> $$FILE; \
	echo "## Stuck" >> $$FILE; echo "" >> $$FILE; \
	echo "## Tomorrow" >> $$FILE; echo "" >> $$FILE; \
	echo "Created: $$FILE"; fi
