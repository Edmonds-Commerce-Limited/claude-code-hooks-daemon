#!/usr/bin/env python3
"""Validate daemon logs against expected handler responses."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class LogValidator:
    """Validates daemon logs against expected responses."""

    def __init__(self, expected_responses_path: Path):
        """Initialize validator with expected responses."""
        with open(expected_responses_path) as f:
            self.expected_responses = yaml.safe_load(f)

        self.handlers = self.expected_responses.get("handlers", {})
        self.test_results: List[Dict[str, Any]] = []

    def parse_daemon_log(self, log_path: Path) -> List[Dict[str, Any]]:
        """
        Parse daemon debug log to extract handler execution events.

        Returns:
            List of handler execution events with structure:
            {
                'handler_name': str,
                'event_type': str,
                'decision': str,
                'reason': str,
                'priority': int,
                'terminal': bool
            }
        """
        events = []

        with open(log_path) as f:
            log_content = f.read()

        # Pattern to extract handler execution from logs
        # This is a simplified pattern - adjust based on actual log format
        handler_pattern = re.compile(
            r"Handler: (\S+).*?"
            r"Decision: (\w+).*?"
            r"Reason: (.+?)(?:\n|$)",
            re.MULTILINE | re.DOTALL,
        )

        for match in handler_pattern.finditer(log_content):
            handler_name = match.group(1)
            decision = match.group(2).lower()
            reason = match.group(3).strip()

            events.append(
                {
                    "handler_name": handler_name,
                    "decision": decision,
                    "reason": reason,
                }
            )

        return events

    def validate_handler_response(
        self, handler_name: str, actual_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate handler responses against expected behavior.

        Args:
            handler_name: Name of handler to validate
            actual_events: List of actual handler execution events from logs

        Returns:
            Validation result with structure:
            {
                'handler': str,
                'passed': bool,
                'tests_run': int,
                'tests_passed': int,
                'tests_failed': int,
                'failures': List[Dict]
            }
        """
        if handler_name not in self.handlers:
            return {
                "handler": handler_name,
                "passed": False,
                "error": f"Handler {handler_name} not found in expected responses",
            }

        expected = self.handlers[handler_name]
        tests = expected.get("tests", [])

        tests_run = len(tests)
        tests_passed = 0
        tests_failed = 0
        failures = []

        for i, test in enumerate(tests):
            test_pattern = test.get("pattern", "")
            expected_decision = test.get("decision", "allow")
            expected_reason_keywords = test.get("reason_contains", [])

            # Find matching event in actual events
            matching_event = None
            for event in actual_events:
                if event["handler_name"] == handler_name:
                    matching_event = event
                    break

            if not matching_event:
                tests_failed += 1
                failures.append(
                    {
                        "test_index": i,
                        "pattern": test_pattern,
                        "reason": "Handler did not execute for this pattern",
                    }
                )
                continue

            # Validate decision
            if matching_event["decision"] != expected_decision:
                tests_failed += 1
                failures.append(
                    {
                        "test_index": i,
                        "pattern": test_pattern,
                        "reason": f"Expected decision '{expected_decision}', got '{matching_event['decision']}'",
                    }
                )
                continue

            # Validate reason contains expected keywords
            reason = matching_event["reason"].lower()
            missing_keywords = []
            for keyword in expected_reason_keywords:
                if keyword.lower() not in reason:
                    missing_keywords.append(keyword)

            if missing_keywords:
                tests_failed += 1
                failures.append(
                    {
                        "test_index": i,
                        "pattern": test_pattern,
                        "reason": f"Reason missing keywords: {missing_keywords}",
                        "actual_reason": matching_event["reason"],
                    }
                )
                continue

            # Test passed
            tests_passed += 1

        return {
            "handler": handler_name,
            "passed": tests_failed == 0,
            "tests_run": tests_run,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "failures": failures,
        }

    def validate_all(self, log_path: Path) -> Dict[str, Any]:
        """
        Validate all handlers against daemon log.

        Args:
            log_path: Path to daemon debug log file

        Returns:
            Validation summary with all results
        """
        actual_events = self.parse_daemon_log(log_path)

        results = []
        total_handlers = 0
        handlers_passed = 0
        handlers_failed = 0

        for handler_name in self.handlers:
            total_handlers += 1
            result = self.validate_handler_response(handler_name, actual_events)
            results.append(result)

            if result.get("passed", False):
                handlers_passed += 1
            else:
                handlers_failed += 1

        return {
            "summary": {
                "total_handlers": total_handlers,
                "handlers_passed": handlers_passed,
                "handlers_failed": handlers_failed,
            },
            "results": results,
        }

    def generate_report(self, validation_results: Dict[str, Any]) -> str:
        """Generate human-readable validation report."""
        summary = validation_results["summary"]
        results = validation_results["results"]

        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("ACCEPTANCE TEST VALIDATION REPORT")
        report_lines.append("=" * 80)
        report_lines.append("")

        # Summary
        report_lines.append("Summary:")
        report_lines.append(f"  Total handlers tested: {summary['total_handlers']}")
        report_lines.append(f"  Handlers passed: {summary['handlers_passed']}")
        report_lines.append(f"  Handlers failed: {summary['handlers_failed']}")
        report_lines.append("")

        # Individual results
        report_lines.append("Handler Results:")
        report_lines.append("-" * 80)

        for result in results:
            handler = result["handler"]
            passed = result.get("passed", False)
            status = "✓ PASS" if passed else "✗ FAIL"

            if "error" in result:
                report_lines.append(f"{status} {handler}: {result['error']}")
            else:
                tests_run = result["tests_run"]
                tests_passed = result["tests_passed"]
                tests_failed = result["tests_failed"]

                report_lines.append(
                    f"{status} {handler} ({tests_passed}/{tests_run} tests passed)"
                )

                if not passed and result.get("failures"):
                    for failure in result["failures"]:
                        report_lines.append(f"    Test {failure['test_index']}:")
                        report_lines.append(f"      Pattern: {failure['pattern']}")
                        report_lines.append(f"      Reason: {failure['reason']}")
                        if "actual_reason" in failure:
                            report_lines.append(
                                f"      Actual: {failure['actual_reason']}"
                            )

        report_lines.append("")
        report_lines.append("=" * 80)

        if summary["handlers_failed"] == 0:
            report_lines.append("✓ ALL TESTS PASSED")
        else:
            report_lines.append(
                f"✗ {summary['handlers_failed']} HANDLER(S) FAILED"
            )

        report_lines.append("=" * 80)

        return "\n".join(report_lines)


def main():
    """Main entry point for validation script."""
    parser = argparse.ArgumentParser(
        description="Validate daemon logs against expected handler responses"
    )
    parser.add_argument(
        "log_file", type=Path, help="Path to daemon debug log file"
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=Path(__file__).parent / "expected-responses.yaml",
        help="Path to expected responses YAML file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for validation report (default: stdout)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )

    args = parser.parse_args()

    if not args.log_file.exists():
        print(f"Error: Log file not found: {args.log_file}", file=sys.stderr)
        return 1

    if not args.expected.exists():
        print(
            f"Error: Expected responses file not found: {args.expected}",
            file=sys.stderr,
        )
        return 1

    # Run validation
    validator = LogValidator(args.expected)
    results = validator.validate_all(args.log_file)

    # Generate output
    if args.json:
        output = json.dumps(results, indent=2)
    else:
        output = validator.generate_report(results)

    # Write output
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Report written to: {args.output}")
    else:
        print(output)

    # Exit with error if any handlers failed
    if results["summary"]["handlers_failed"] > 0:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
