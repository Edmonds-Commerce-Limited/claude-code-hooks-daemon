"""SessionStart event handlers."""

from . import secret_file_hygiene_checker as _secret_file_hygiene_checker_module
from .ccy_supervisor_integrity import CcySupervisorIntegrityHandler
from .config_optimisation_reminder import ConfigOptimisationReminderHandler
from .contract_staleness import ContractStalenessHandler
from .disclosure_reset_session_start import DisclosureResetSessionStartHandler
from .git_filemode_checker import GitFilemodeCheckerHandler
from .git_upstream_checker import GitUpstreamCheckerHandler
from .gitignore_safety_checker import GitignoreSafetyCheckerHandler
from .hook_registration_checker import HookRegistrationCheckerHandler
from .model_fallback_detector import ModelFallbackDetectorHandler
from .optimal_config_checker import OptimalConfigCheckerHandler
from .plan_qa_sweep import PlanQaSweepHandler
from .project_handler_load_checker import ProjectHandlerLoadCheckerHandler
from .remote_docs_staleness import RemoteDocsStalenessHandler
from .skill_opportunity_detector import SkillOpportunityDetectorHandler
from .suggest_statusline import SuggestStatusLineHandler
from .tool_disable_advisor import ToolDisableAdvisorHandler
from .version_check import VersionCheckHandler

SecretFileHygieneCheckerHandler = (
    _secret_file_hygiene_checker_module.SecretFileHygieneCheckerHandler
)

__all__ = [
    "CcySupervisorIntegrityHandler",
    "ConfigOptimisationReminderHandler",
    "ContractStalenessHandler",
    "DisclosureResetSessionStartHandler",
    "GitFilemodeCheckerHandler",
    "GitUpstreamCheckerHandler",
    "GitignoreSafetyCheckerHandler",
    "HookRegistrationCheckerHandler",
    "ModelFallbackDetectorHandler",
    "OptimalConfigCheckerHandler",
    "PlanQaSweepHandler",
    "ProjectHandlerLoadCheckerHandler",
    "RemoteDocsStalenessHandler",
    "SecretFileHygieneCheckerHandler",
    "SkillOpportunityDetectorHandler",
    "SuggestStatusLineHandler",
    "ToolDisableAdvisorHandler",
    "VersionCheckHandler",
]
