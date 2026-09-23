# Fabric consumer starter

1. Copy `ci.yml` and `cd.yml` to the new repository's `.azure-pipelines/` folder.
2. Copy `config.json` to `.fabric/config.json`. Replace the project name, owner,
   source workspace ID, target workspace IDs and service connection names.
3. Export the managed Lakehouse/Notebook definitions under `items/`, or update
   `itemRoots`. Keep their `.platform` metadata. For Report/SemanticModel projects,
   use the analytics consumer's external lakehouse/connection declarations and
   `allowedItemTypes` instead; see the [Fabric guide](../../docs/fabric/README.md).
4. Register `<project>-ci` and `<project>-cd`, matching the `fabricCI` resource's
   source name. Configure environment checks and permissions before enabling CD.

This is a configuration starter, not an example containing deployable user data.
CI should fail until the owner and source definitions are supplied. It can then
generate inventories while target workspace IDs remain placeholders. CD requires
complete target configuration. Pin both platform refs to the same tested release.
