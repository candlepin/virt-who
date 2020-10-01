#!/bin/bash
set -e
git format-patch HEAD..remove_ahv_support || git format-patch HEAD..origin/remove_ahv_support
mv 0001*.patch build-rpm-no-ahv.patch
echo "If the patch does not cleanly apply, merge master into the remove_ahv_support branch, fix any conflicts, squash to a single commit and re-run the script."
