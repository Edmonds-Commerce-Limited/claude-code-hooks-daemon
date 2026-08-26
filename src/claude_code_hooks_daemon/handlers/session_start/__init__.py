"""SessionStart event handlers."""

from . import secret_file_hygiene_checker as _secret_file_hygiene_checker_module
from .ccy_supervisor_integrity import CcySupervisorIntegrityHandler
from .contract_staleness import ContractStalenessHandler
from .git_filemode_checker import GitFilemodeCheckerHandler
from .git_upstream_checker import GitUpstreamCheckerHandler
from .gitignore_safety_checker import GitignoreSafetyCheckerHandler
from .hook_registration_checker import HookRegistrationCheckerHandler
from .optimal_config_checker import OptimalConfigCheckerHandler
from .plan_qa_sweep import PlanQaSweepHandler
from .project_handler_load_checker import ProjectHandlerLoadCheckerHandler
from .skill_opportunity_detector import SkillOpportunityDetectorHandler
from .suggest_statusline import SuggestStatusLineHandler
from .version_check import VersionCheckHandler

SecretFileHygieneCheckerHandler = (
    _secret_file_hygiene_checker_module.SecretFileHygieneCheckerHandler
)

__all__ = [
    "CcySupervisorIntegrityHandler",
    "ContractStalenessHandler",
    "GitFilemodeCheckerHandler",
    "GitUpstreamCheckerHandler",
    "GitignoreSafetyCheckerHandler",
    "HookRegistrationCheckerHandler",
    "OptimalConfigCheckerHandler",
    "PlanQaSweepHandler",
    "ProjectHandlerLoadCheckerHandler",
    "SecretFileHygieneCheckerHandler",
    "SkillOpportunityDetectorHandler",
    "SuggestStatusLineHandler",
    "VersionCheckHandler",
]
