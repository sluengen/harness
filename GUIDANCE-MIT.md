# Guidance licence (MIT)

Copyright (c) 2026 Scott Luengen

The harness's own code is licensed under the GNU Affero General Public License v3.0
(see [`LICENSE`](./LICENSE)). This file is the exception: the guidance files the
installer copies into other repositories are **MIT**-licensed, and the MIT terms
alone govern them. This file is named off any `licen[sc]e`/`copying` stem on
purpose — GitHub's licence detector resolves a repo to a single licence, so a
second root file named `LICENSE-*` would make it report "Other" for the whole
repo. Why the split exists, and what it means for you, is in
[`README.md`](./README.md) and [`CONTRIBUTING.md`](./CONTRIBUTING.md).

SPDX-License-Identifier: MIT

Scope -- "the Software" below means every file under these paths:

    agents/
    commands/
    hooks/
    process/
    settings/
    skills/
    templates/

The authoritative boundary is the `files:` block of `registry.yaml`, which by
construction enumerates exactly what the installer copies into a consuming repo.
The paths above are the directories that block spans; `registry.yaml` governs if
the two ever disagree, and a test holds them in correspondence
(tests/unit/test_license_boundary.py). Everything outside these paths -- the
verification gate and its instrument in `scripts/`, and the guards in `tests/`
-- is the harness's own code, and is AGPL-3.0-only.

--------------------------------------------------------------------------

MIT License

Copyright (c) 2026 Scott Luengen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
