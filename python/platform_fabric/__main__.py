import argparse
import os

from .inventory import generate, read_json, write_inventory
from .release import build, pipeline_provenance, verify


def main():
    parser = argparse.ArgumentParser(description="Fabric inventory and immutable promotion")
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--root", required=True)
    inventory.add_argument("--output", required=True)
    package = commands.add_parser("build")
    package.add_argument("--root", required=True)
    package.add_argument("--output", required=True)
    check = commands.add_parser("verify")
    check.add_argument("--release", required=True)
    review = commands.add_parser("review")
    review.add_argument("--release", required=True)
    review.add_argument("--environment", required=True, choices=["dev", "test", "prod"])
    review.add_argument("--url", required=True)
    review.add_argument("--receipt", required=True)
    review.add_argument("--policy-digest")
    promote = commands.add_parser("deploy")
    promote.add_argument("--release", required=True)
    promote.add_argument("--environment", required=True, choices=["dev", "test", "prod"])
    promote.add_argument("--receipt", required=True)
    promote.add_argument("--policy-review")
    promote.add_argument("--policy-mode", choices=["passing", "all"], default="passing")
    promote.add_argument("--policy-digest")
    args = parser.parse_args()
    if args.command == "inventory":
        manifest, graph = generate(args.root, read_json(args.root + "/.fabric/config.json"))
        write_inventory(args.output, manifest, graph)
    elif args.command == "build":
        build(args.root, args.output, pipeline_provenance())
    else:
        expected = {k: os.environ[e] for k, e in {
            "buildId": "CI_RUN_ID", "sourceVersion": "CI_SOURCE_VERSION",
            "repositoryId": "CI_REPOSITORY_ID", "sourceBranch": "CI_SOURCE_BRANCH",
        }.items()}
        if args.command == "verify":
            verify(args.release, expected)
        elif args.command == "review":
            from .policy import review
            review(args.release, args.environment, args.url, args.receipt, expected, args.policy_digest)
        else:
            from .deploy import deploy
            deploy(args.release, args.environment, args.receipt, expected,
                   policy_review=args.policy_review, policy_mode=args.policy_mode, policy_digest=args.policy_digest)


if __name__ == "__main__":
    main()
