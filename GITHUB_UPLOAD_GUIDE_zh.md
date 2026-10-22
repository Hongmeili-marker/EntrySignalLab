# EntrySignalLab：GitHub 上传说明

整理日期：2026-10-22。目标仓库：https://github.com/Hongmeili-marker/EntrySignalLab

## 上传哪一层

解压本包后，打开 EntrySignalLab 文件夹。把其中的文件和文件夹放到仓库根目录：README.md、pyproject.toml、src、tests、examples、docs、scripts、dist、.github 等应直接位于仓库根目录。
不要把外层 EntrySignalLab 文件夹再作为子目录上传；不要只把 ZIP 文件放进仓库。

本目录共 207 个文件，包含 .github/workflows/tests.yml 和 .gitignore。使用文件管理器时须确认这些以点开头的项目也被包含。

## 原压缩包各部分如何处理

| 原包位置 | 放在哪里 | 原因 |
| --- | --- | --- |
| public_release/EntrySignalLab-0.25.0/ 内的内容 | GitHub 仓库根目录 | 正式软件源码、测试、示例和说明 |
| original_release/EntrySignalLab_v0.25.0_Software.zip | 本地归档；需要时可作为 Release 历史附件 | 与公开源码有大量相同内容，不再解压一份放进仓库 |
| publication/ | 投稿工作目录；决定公开论文时再单独发布 | 包含 Word、Markdown、LaTeX、PDF 和图稿，是同一论文的不同交付格式 |
| evidence/ | 本地保存；需要公开时作为独立 Release 附件 | 是运行结果和验证记录，不是运行软件必需的源码 |
| 外层 build_submission.py、original_build_documents.py、START_HERE.txt、SUBMISSION_PREPARATION_RECEIPT.json、SHA256SUMS.txt | 本地保留 | 面向整个投稿总包，不能与仓库内的同名清单混用 |

publication/ 根目录和 publication/figures/ 中有 5 对 PDF 内容完全相同；用于不同排版打包路径。没有把这些论文材料加入本上传包，也未删除原件。

## 不要因为版本号不同就删除

src/ 中 14 个 Python 模块是运行源码；dist/ 中的 wheel 是可安装发行包。两者用途不同。当前 QUICKSTART 和部分验证脚本引用这个 wheel，所以这里保留。
tests/ 下旧版本命名的测试和数据是回归验证资料；docs/ 下验收记录、scripts/ 下验证程序也有引用关系，保留整套，不按版本号删除。
CITATION.cff 和 CITATION.cff.template 均已填入作者姓名、单位和邮箱；现有发布核查脚本仍引用后者，因此两份保留。

## 这次整理做了什么

1. 使用原包公开源码目录的全部 205 个文件。
2. 保留已检查 GitHub 提交 c00223bd87a0f6d335682f4a3d46faa743618bb9 中的 README.md、pyproject.toml、.gitignore 和已填写的 CITATION.cff。
3. 补回该提交缺失的 18 个 examples 配置文件及 5 个 docs 验收文档。
4. 调整 .gitignore：继续忽略其他 dist 产物，但允许跟踪指定 v0.25.0 wheel。
5. 增加本说明，并重新生成根目录 SHA256SUMS.txt。清单核对本包实际文件字节，不代表再次执行全部测试或验收。
6. 全部 14 个运行模块均与原公开源码包逐字节相同，没有改动算法。当前上传包的 wheel 已重新构建，以同步作者和公开仓库元数据。

## 上传方式

推荐用 GitHub Desktop：先克隆现有仓库，把本文件夹内的内容复制到本地仓库根目录，查看 Changes 后提交并 Push。不要删除本地 .git 目录，不要使用强制推送。如果仓库在本次检查之后有新提交，先同步并核对新改动，不要盲目覆盖。

如果使用 GitHub 网页 Add file → Upload files，可按 docs、examples、scripts、tests、src 等目录分批上传；每次保留完整相对路径。文件较多时优先使用 GitHub Desktop，以减少漏选和路径错误。README.md 必须能在仓库首页直接展示。

## 上传之后

确认新增的 examples/source_baseline.json、examples/uncertainty.json、docs/v0250_acceptance.md 均可打开；确认 Actions 工作流实际启动并检查结果。未取得成功结果前，不宣称多平台 CI 已通过。

以下事项尚需作者另行完成：原始论文完整参考信息、固定版本发布链接及投稿声明。此包仅整理仓库内容，没有创建 GitHub Release、DOI 或提交论文。

如建立 Release，可上传经确认的完整软件源码 ZIP 和 wheel；论文及 evidence 是否公开由作者决定，不必把整份投稿总包提交进源码仓库。

## 作者信息更新

已按用户提供的信息统一填写：Hongmei Li；School of Medical Information Engineering, Shenyang Medical College, Shenyang, China；Hongmeili@symc.edu.cn。信息已覆盖中英文 README、CITATION.cff 及其模板、pyproject.toml 和发布清单。pyproject.toml 已有正确姓名与邮箱，保留原内容。单位记录在 README 和 CFF 中，未向标准项目作者字段添加不受支持的 affiliation 键。保留原 MIT 版权行。当前上传包的 wheel 已从未改动的运行模块重新构建，同步作者与公开仓库元数据；原始验证收据继续指向原冻结版，不代表元数据修订版的整包哈希。

## 公开仓库信息更新

已填写公开仓库：https://github.com/Hongmeili-marker/EntrySignalLab，并同步到 README、CITATION.cff 及模板、pyproject.toml 和发布清单。当前尚无经确认的版本 Release 链接或 DOI，未填入虚构链接。原作者及仓库未填写的历史叙述保留为历史记录，并添加当前状态说明。
