"""The MCP tool surface: which public tools each domain registers, and which of them serves an action.

Every domain class (``AlertManagement``, ``CustomerManagement``, ...) answers to
one internal ``key``. A domain whose actions both read and change data is
published as two tools, a read-only one and a write one, so that each tool can
carry a truthful ``readOnlyHint`` or ``destructiveHint``. A domain that only
reads is published once.

Each domain lists its ``write_actions``. Any other action is a read when its
name starts with one of ``READ_ACTION_PREFIXES`` or the domain lists it in
``read_overrides``. ``tests/unit/test_tool_surface.py`` fails when a domain
class advertises an action that is neither listed as a write nor read by that
rule, so every advertised action has exactly one serving tool; a name the
class does not advertise is refused by the class itself.
"""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from .department_aliases import DEPRECATED_ACTION_ALIASES

READ_ACTION_PREFIXES: Tuple[str, ...] = (
    "analy",
    "check",
    "clarify",
    "detect",
    "discover",
    "estimate",
    "find",
    "get",
    "help",
    "list",
    "lookup",
    "parse",
    "preview",
    "query",
    "resolve",
    "search",
    "show",
    "suggest",
    "validate",
    "verify",
)


class ToolSide(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolDomain:
    key: str
    title: str
    read_name: str
    read_description: str
    write_name: Optional[str] = None
    write_description: Optional[str] = None
    write_title: Optional[str] = None
    write_actions: FrozenSet[str] = frozenset()
    read_overrides: FrozenSet[str] = frozenset()

    @property
    def sides(self) -> Tuple[ToolSide, ...]:
        if self.write_name is None:
            return (ToolSide.READ,)
        return (ToolSide.READ, ToolSide.WRITE)

    @property
    def public_names(self) -> Tuple[str, ...]:
        return tuple(self.name_for(side) for side in self.sides)

    def name_for(self, side: ToolSide) -> str:
        if side is ToolSide.WRITE and self.write_name:
            return self.write_name
        return self.read_name

    def title_for(self, side: ToolSide) -> str:
        if side is ToolSide.READ:
            return self.title
        return self.write_title or f"Manage {self.title}"

    def description_for(self, side: ToolSide) -> str:
        if side is ToolSide.WRITE and self.write_description:
            return self.write_description
        return self.read_description

    def reads_by_rule(self, action: str) -> bool:
        return action in self.read_overrides or action.startswith(READ_ACTION_PREFIXES)

    def side_of(self, action: str) -> ToolSide:
        resolved = DEPRECATED_ACTION_ALIASES.get(action, action)
        if resolved not in self.write_actions and self.reads_by_rule(resolved):
            return ToolSide.READ
        return ToolSide.WRITE

    def serving_side(self, action: str) -> Optional[ToolSide]:
        """The side that serves a listed write or a read by the rule; None for any other name."""
        resolved = DEPRECATED_ACTION_ALIASES.get(action, action)
        if resolved in self.write_actions:
            return ToolSide.WRITE
        if self.reads_by_rule(resolved):
            return ToolSide.READ
        return None

    def tool_for(self, action: str) -> str:
        """The public tool that serves ``action``."""
        return self.name_for(self.side_of(action))

    def actions_served_by(self, public_name: str, actions: Iterable[str]) -> List[str]:
        """The ``actions`` the public tool ``public_name`` runs; its sibling refuses the rest."""
        return [action for action in actions if self.tool_for(action) == public_name]

    def sibling_of(self, public_name: str) -> Optional[str]:
        """The other public tool of a split domain; None for a domain published once."""
        if self.write_name is None:
            return None
        return self.read_name if public_name == self.write_name else self.write_name


TOOL_DOMAINS: Tuple[ToolDomain, ...] = (
    ToolDomain(
        key="manage_system_setup",
        title="System Setup",
        read_name="get_system_setup",
        read_description=(
            "Shows the setup checklist, configuration status and onboarding guidance "
            "for this Revenium connection. Not for platform data such as costs or customers."
        ),
        write_name="manage_system_setup",
        write_description=(
            "Changes this server's local setup, such as the notification email on a "
            "self-hosted server. Not for alerts, customers or other platform data."
        ),
        write_actions=frozenset({"update_email"}),
        read_overrides=frozenset(
            {
                "complete_setup",
                "environment_status",
                "next_steps",
                "setup_checklist",
                "setup_guidance",
                "test_configuration",
            }
        ),
    ),
    ToolDomain(
        key="manage_slack",
        title="Alert Channels (Slack)",
        read_name="get_slack",
        read_description=(
            "Lists the Slack channels connected for alert notifications and returns the "
            "link and steps to connect a new workspace. Not for creating alerts."
        ),
        write_name="manage_slack",
        write_description=(
            "Chooses the default Slack channel that alert notifications use. "
            "Not for connecting a workspace, which happens in the browser."
        ),
        write_actions=frozenset(
            {
                "select_default_configuration",
                "set_default_configuration",
            }
        ),
        read_overrides=frozenset(
            {
                "first_time_guidance",
                "guided_setup",
                "initiate_oauth",
                "onboarding_setup",
                "quick_setup",
                "refresh_configurations",
                "setup_status",
            }
        ),
    ),
    ToolDomain(
        key="tool_introspection",
        title="Tool Introspection",
        read_name="tool_introspection",
        read_description=(
            "Lists the tools this server offers and returns the metadata of one of them. "
            "Not for Revenium platform data."
        ),
    ),
    ToolDomain(
        key="get_capabilities",
        title="Capabilities",
        read_name="get_capabilities",
        read_description=(
            "Returns the values the platform accepts for each resource type, such as "
            "currencies, plan types and metrics. Not for reading the resources themselves."
        ),
        read_overrides=frozenset({"manage_capabilities", "refresh_capabilities"}),
    ),
    ToolDomain(
        key="manage_alerts",
        title="Guardrails: Alerts",
        read_name="get_alerts",
        read_description=(
            "Lists and reads spending alerts, alert history, budget progress and anomalies. "
            "Not for changing alerts; manage_alerts does that."
        ),
        write_name="manage_alerts",
        write_description=(
            "Creates, updates, enables, disables and deletes spending alerts and resets budgets. "
            "Not for reading alerts; get_alerts does that."
        ),
        write_actions=frozenset(
            {
                "clear_all",
                "create",
                "create_cumulative_usage_alert",
                "create_from_text",
                "create_simple",
                "create_threshold_alert",
                "delete",
                "disable",
                "disable_all",
                "disable_multiple",
                "enable",
                "enable_all",
                "enable_multiple",
                "reset_budget",
                "toggle_status",
                "update",
            }
        ),
    ),
    ToolDomain(
        key="manage_ai_insights",
        title="Intelligence",
        read_name="get_ai_insights",
        read_description=(
            "Reads AI cost-intelligence runs, their findings and the feedback given on them. "
            "Not for starting a run; manage_ai_insights does that."
        ),
        write_name="manage_ai_insights",
        write_description=(
            "Starts an AI cost-intelligence run or records feedback on a recommendation. "
            "Not for reading results; get_ai_insights does that."
        ),
        write_actions=frozenset({"submit_feedback", "trigger_run"}),
    ),
    ToolDomain(
        key="get_business_analytics",
        title="Costs & Revenue",
        read_name="get_business_analytics",
        read_description=(
            "Reports AI costs and revenue broken down by provider, model, customer, agent, "
            "user, department or tool, plus invoices and PR health. Not for individual transactions."
        ),
    ),
    ToolDomain(
        key="manage_metering",
        title="Logs and Metering",
        read_name="get_metering",
        read_description=(
            "Looks up metered AI transactions, supported models and integration guides. "
            "Not for sending a transaction; manage_metering does that."
        ),
        write_name="manage_metering",
        write_description=(
            "Submits an AI transaction to Revenium metering. "
            "Not for looking transactions up; get_metering does that."
        ),
        write_actions=frozenset({"submit_ai_transaction"}),
    ),
    ToolDomain(
        key="manage_customers",
        title="Customers",
        read_name="get_customers",
        read_description=(
            "Lists and reads organizations, subscribers, users, teams, departments and "
            "their settings. Not for changing them; manage_customers does that."
        ),
        write_name="manage_customers",
        write_description=(
            "Creates, updates and deletes organizations, subscribers, users, teams and "
            "department assignments, and changes their settings. Not for reading them."
        ),
        write_actions=frozenset(
            {
                "add_verified_domain",
                "clear_department_assignment",
                "create",
                "delete",
                "delete_department_person",
                "remove_verified_domain",
                "update",
                "update_attribution_identity_policy",
                "update_marketplace_settings",
                "update_pr_health_digest_settings",
                "update_pr_health_settings",
            }
        ),
    ),
    ToolDomain(
        key="manage_products",
        title="Products",
        read_name="get_products",
        read_description=(
            "Lists and reads products, their pricing, templates and subscriptions. "
            "Not for changing products; manage_products does that."
        ),
        write_name="manage_products",
        write_description=(
            "Creates, updates and deletes products. Not for reading them; get_products does that."
        ),
        write_actions=frozenset(
            {
                "create",
                "create_simple",
                "create_with_subscription",
                "delete",
                "update",
            }
        ),
    ),
    ToolDomain(
        key="manage_sources",
        title="Cost Sources and Revenue Sources",
        read_name="get_sources",
        read_description=(
            "Lists and reads the sources that feed cost and revenue data. "
            "Not for changing them; manage_sources does that."
        ),
        write_name="manage_sources",
        write_description=(
            "Creates, updates and deletes cost and revenue sources. "
            "Not for reading them; get_sources does that."
        ),
        write_actions=frozenset({"create", "delete", "update"}),
    ),
    ToolDomain(
        key="manage_usage_meters",
        title="Usage Meters",
        read_name="get_usage_meters",
        read_description=(
            "Lists and reads usage meters and meter templates. "
            "Not for changing meters; manage_usage_meters does that."
        ),
        write_name="manage_usage_meters",
        write_description=(
            "Creates, updates and deletes usage meters. "
            "Not for reading them; get_usage_meters does that."
        ),
        write_actions=frozenset(
            {
                "create",
                "create_from_template",
                "delete",
                "update",
            }
        ),
    ),
    ToolDomain(
        key="manage_subscriptions",
        title="Subscriptions",
        read_name="get_subscriptions",
        read_description=(
            "Lists, searches and reads subscriptions, their usage, quotas and billed amounts. "
            "Not for changing them; manage_subscriptions does that."
        ),
        write_name="manage_subscriptions",
        write_description=(
            "Creates, updates and deletes subscriptions. "
            "Not for reading them; get_subscriptions does that."
        ),
        write_actions=frozenset({"create", "delete", "update"}),
        read_overrides=frozenset({"subscription_nlp"}),
    ),
    ToolDomain(
        key="manage_credentials",
        title="Credentials",
        read_name="get_credentials",
        read_description=(
            "Lists and reads subscriber credentials and the guidance for setting them up. "
            "Not for changing them; manage_credentials does that."
        ),
        write_name="manage_credentials",
        write_description=(
            "Creates, updates and deletes subscriber credentials. "
            "Not for reading them; get_credentials does that."
        ),
        write_actions=frozenset({"create", "delete", "update"}),
    ),
    ToolDomain(
        key="manage_workflows",
        title="Workflows",
        read_name="get_workflows",
        read_description=(
            "Lists workflow templates and reads the state and next step of a running workflow. "
            "Not for starting or advancing one; manage_workflows does that."
        ),
        write_name="manage_workflows",
        write_description=(
            "Starts a guided workflow or marks one of its steps complete. "
            "Not for reading workflows; get_workflows does that."
        ),
        write_actions=frozenset({"complete_step", "start"}),
        read_overrides=frozenset({"next_step"}),
    ),
    ToolDomain(
        key="manage_jobs",
        title="All Jobs",
        read_name="get_jobs",
        read_description=(
            "Lists and reads jobs, their transactions, ROI, conversion funnels and job type "
            "economics. Not for reporting outcomes; manage_jobs does that."
        ),
        write_name="manage_jobs",
        write_description=(
            "Reports and amends job outcomes, period facts, job type economics and baselines. "
            "Not for reading jobs; get_jobs does that."
        ),
        write_actions=frozenset(
            {
                "amend_outcome",
                "append_outcome_metrics",
                "create_job_type_baseline",
                "report_outcome",
                "report_period_facts",
                "upsert_job_type_economics",
            }
        ),
    ),
    ToolDomain(
        key="manage_tools",
        title="Tool Registry",
        read_name="get_tools",
        read_description=(
            "Lists and reads registered tools, their usage events, costs, latency and "
            "success rate. Not for changing the registry; manage_tools does that."
        ),
        write_name="manage_tools",
        write_description=(
            "Registers, updates and deletes tools and records tool usage events. "
            "Not for reading the registry; get_tools does that."
        ),
        write_actions=frozenset(
            {
                "create",
                "create_simple",
                "delete",
                "meter_event",
                "record_event",
                "replace",
                "update",
            }
        ),
    ),
    ToolDomain(
        key="manage_agents",
        title="Agent Squads",
        read_name="get_agents",
        read_description=(
            "Lists and reads registered and discovered agents, squads and squad executions. "
            "Not for changing agents; manage_agents does that."
        ),
        write_name="manage_agents",
        write_description=(
            "Registers, updates and deletes agents. Not for reading them; get_agents does that."
        ),
        write_actions=frozenset({"create", "delete", "update"}),
    ),
    ToolDomain(
        key="manage_cost_controls",
        title="Guardrails: Cost Controls",
        read_name="get_cost_controls",
        read_description=(
            "Lists and reads spend limits and the enforcement events and rules they produce. "
            "Not for changing limits; manage_cost_controls does that."
        ),
        write_name="manage_cost_controls",
        write_description=(
            "Creates, updates and deletes spend limits that warn or block when crossed. "
            "Not for reading them; get_cost_controls does that."
        ),
        write_actions=frozenset({"create", "delete", "update"}),
    ),
    ToolDomain(
        key="system_diagnostics",
        title="System Diagnostics",
        read_name="system_diagnostics",
        read_description=(
            "Checks this connection's health, configuration and logs, including ingestion "
            "failures. Not for changing tenant settings; manage_system_settings does that."
        ),
        write_name="manage_system_settings",
        write_title="System Settings",
        write_description=(
            "Turns tenant-wide settings on or off: strict ingestion mode, usage-based billing "
            "and attribution detail text. Not for diagnostics; system_diagnostics does that."
        ),
        write_actions=frozenset(
            {
                "set_attribution_detail_text",
                "set_strict_ingestion_mode",
                "set_usage_billing",
            }
        ),
        read_overrides=frozenset(
            {
                "auto_discovery",
                "debug",
                "environment_variables",
                "onboarding_status",
                "system_health",
            }
        ),
    ),
)

DOMAINS_BY_KEY: Mapping[str, ToolDomain] = MappingProxyType(
    {domain.key: domain for domain in TOOL_DOMAINS}
)


def _domains_by_public_name() -> Dict[str, ToolDomain]:
    return {name: domain for domain in TOOL_DOMAINS for name in domain.public_names}


DOMAINS_BY_PUBLIC_NAME: Mapping[str, ToolDomain] = MappingProxyType(
    _domains_by_public_name()
)

ALL_PUBLIC_TOOL_NAMES: Tuple[str, ...] = tuple(DOMAINS_BY_PUBLIC_NAME)


def domain_for(name: str) -> ToolDomain:
    """The domain a public tool name or a domain key belongs to."""
    domain = DOMAINS_BY_KEY.get(name) or DOMAINS_BY_PUBLIC_NAME.get(name)
    if domain is None:
        raise KeyError(f"Unknown tool or domain: {name}")
    return domain


def side_of_tool(public_name: str) -> ToolSide:
    domain = domain_for(public_name)
    return ToolSide.WRITE if public_name == domain.write_name else ToolSide.READ


def public_tool_for(name: str, action: str) -> str:
    """The public tool that serves ``action`` of the domain ``name`` belongs to."""
    return domain_for(name).tool_for(action)


def tool_call(name: str, action: str, **arguments: object) -> str:
    """Render a call of ``action`` on the public tool that serves it, for help text."""
    rendered = "".join(
        f", {argument}={value!r}" for argument, value in arguments.items()
    )
    return f"{public_tool_for(name, action)}(action='{action}'{rendered})"
