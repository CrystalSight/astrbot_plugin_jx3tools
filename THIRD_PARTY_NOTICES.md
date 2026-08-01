# Third-party notices

The MIT License in this repository applies to the JX3Tools source code and
project-owned documentation. The third-party game art, fonts, names,
trademarks, APIs, and other materials described below are not covered by the
MIT License.

## JX3BOX thumbnails (not distributed)

The maintainer's local working copy may contain 72 px thumbnails derived from
images served by JX3BOX in the following directories:

- `assets/adventures/`
- `assets/bosses/`

Source catalogues and image endpoints:

- <https://node.jx3box.com/serendipities>
- <https://node.jx3box.com/monster/boss>
- <https://img.jx3box.com/adventure/>
- <https://img.jx3box.com/pve/baizhan/>

Repository and license research performed on 2026-08-01:

- [`JX3BOX/img-pve`](https://github.com/JX3BOX/img-pve) contains the matching
  `baizhan/` image family, but has no root license or GitHub-detected license.
- [`JX3BOX/img-oss`](https://github.com/JX3BOX/img-oss) documents the public
  image-mirror layout, but has no root license or GitHub-detected license; its
  public tree does not contain the matching adventure thumbnail set.
- The relevant `JX3BOX/pvx`, `JX3BOX/pvx_v1`, and `JX3BOX/pvx_v2` repositories
  also have no root license or GitHub-detected license.
- `JX3BOX/jx3box-data` declares MIT in its package metadata, but it is a
  separate data package and does not license the image files listed above.
- No organization-wide license grant was found in the JX3BOX organization
  profile or the inspected repositories. GitHub's
  [licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
  explains that a public repository without a license does not itself grant
  redistribution rights.

Authorization status: **no redistribution grant found**. All PNG files in the
two directories above are therefore excluded from Git and are not distributed
in the public repository. This exclusion removes the asset-authorization block
for the first source-code push; it does not grant permission to redistribute
local copies.

JX3Tools is not affiliated with or endorsed by JX3BOX, Kingsoft, Seasun, or the
operators of JX3API. All third-party names, trademarks, and artwork remain the
property of their respective owners.

## Alibaba PuHuiTi 3

Alibaba PuHuiTi 3 font files are not distributed in this repository. Users must
obtain the font from its official distribution and comply with its terms. The
plugin only reads administrator-provided copies from AstrBot's plugin data
directory.
