# EntrySignalLab：跨环境 CI 修复说明

日期：2026-10-22。基于仓库提交 3ed1d07743407cca9b3128761fdae9d66817d6c7。

## 修改内容

- .github/workflows/tests.yml：保留原有七个兼容性任务，增加 Linux/Python 3.12 锁定依赖的严格回放任务。没有删除失败环境，也没有把任务失败改成忽略。
- scripts/validation_portability.py：统一跨环境验证契约；策略与状态、收益符号、零与非零保持严格检查。相对数值容差为 2e-11，控制量容差为 2e-7，不增加固定的绝对经济容差。另行核验配置边界、精确有理数或 200/400 位独立积分、真实比较记录的金额、符号和容差区间。显示净收益可能继承毛收入/成本分量的舍入误差，此显示误差按独立分量的 64 ULP 限定；经济排序仍由原始输入参考值核验。
- tests/test_v0220_audit.py、test_v0230_audit.py、test_v0250_audit.py，以及对应 validate_v0220.py、validate_v0230.py、validate_v0250.py：同时修复单元测试与后续验证，避免只通过前一步。执行次数、排序比较调用顺序和依赖具体返回控制点的残差，不再当作跨解释器完全相同的科学结果；实际控制点上的导数和探测记录仍单独核验。
- tests/test_v0100_audit.py、scripts/validate_v0100.py：清点活动锁文件时核验文件身份、大小和修改时间，不读取 Windows 正在锁住的字节；其他实验文件仍核验内容哈希。
- scripts/validate_repairs.py：将冷启动 CLI 和辅助进程的等待上限调整为有界的 60 秒，避免并发或较慢机器在导入科学库时触发原 15 秒超时；没有放宽求解器的收敛条件或评估预算。
- scripts/run_tests.py：失败详情直接输出到 Actions 控制台，并记录验证策略及辅助脚本哈希。
- scripts/release_evidence.py：将新增验证辅助脚本纳入发布输入哈希。
- tests/test_ci_portability.py：新增 10 项反例，验证错误收益、越界控制、错误策略、收益符号或零状态改变、错误比较金额或符号等不会被容差掩盖；模拟 Windows 禁止读取锁文件，同时确认普通文件变动仍能检测。

## 验证范围

完整本地实测记录见 docs/ci_portability_validation.json。运行环境包括 Linux/Python 3.10.22（最低依赖）、3.12.14（原锁定科学环境、严格回放）和 3.13.16（较新依赖）。三个环境各实际运行 917 项测试，均零失败、零错误、零跳过。

Windows 锁文件读取限制有针对性的模拟反例，但本机没有运行原生 Windows 或 macOS。上传后须依据新的远程 Actions 判断这两个系统及整个矩阵是否通过；此包不预先宣称远程全绿。

14 个运行模块、所有原始测试数据及示例输入不变。wheel 仅重新打包，以同步当前说明和作者/仓库元数据。原始 907 项测试及历史完整发行的验证记录仍属于原冻结版本，不作为这次修改的整包哈希或远程通过证明。

## 上传

打开解压后的 EntrySignalLab 文件夹，将其内容放入仓库根目录；覆盖同名文件并加入新文件。必须包含 .github/workflows/tests.yml、.gitignore、新的 scripts/validation_portability.py 和 tests/test_ci_portability.py。上传后查看新一轮 Actions，不必手动反复重跑旧提交。

## 覆盖或新增的文件

- `.github/workflows/tests.yml`
- `CHANGELOG.md`
- `CI_FIX_NOTES_zh.md`
- `GITHUB_UPLOAD_GUIDE_zh.md`
- `QUICKSTART.md`
- `README.md`
- `README_zh.md`
- `RELEASE_CHECKLIST.md`
- `SHA256SUMS.txt`
- `dist/entrysignallab-0.25.0-py3-none-any.whl`
- `docs/api.md`
- `docs/ci_portability_validation.json`
- `scripts/release_evidence.py`
- `scripts/run_tests.py`
- `scripts/validate_repairs.py`
- `scripts/validate_v0100.py`
- `scripts/validate_v0220.py`
- `scripts/validate_v0230.py`
- `scripts/validate_v0250.py`
- `scripts/validation_portability.py`
- `tests/test_ci_portability.py`
- `tests/test_v0100_audit.py`
- `tests/test_v0220_audit.py`
- `tests/test_v0230_audit.py`
- `tests/test_v0250_audit.py`

## 第二轮远程检查与修复（2026-10-22）

核对提交 `85aa09e135f5dade02ac851420e6617103328d95`：211 个 Git blob 全部与第一轮修复包一致，无漏传。远程 run 39774585310 中仍观察到两类失败：

- macOS/Python 3.13：`validate_v0160.py` 的 39 项普通 Wilson 区间冻结比较中，7 项要求浮点完全相等而失败。独立 400 位 Wilson 验证均通过。改为同时核验冻结数值容差与独立参考区间；零端点、有效区间和独立参考检查保留。锁定环境仍精确比较，并在 locked-reference 任务加入此验证器。
- Windows/Python 3.12：`validate_v0220.py` 在冻结 JSON 的原始 SHA256 检查失败。下载证据中的运行模块哈希与 CRLF 转换后的文件完全一致，而非原 LF 字节。新增 `.gitattributes`，强制文本检出 LF，保留二进制文件；不修改原数据、原哈希，也不绕过完整性检查。这也防止后续 v0.23/0.24/0.25 的冻结输入检查遇到同一问题。

对 Git `core.autocrlf=true` 实际建库、加入、删除并重新检出 45 个源文件、冻结数据和 wheel，字节全部保持不变；v0.21/v0.24 冻结输入哈希全部通过。新增两项测试验证 Wilson 区间错误不能被容差掩盖，严格回放仍保持完全相等。最新本地实测附加在 `docs/ci_portability_validation.json` 的 `remote_followup` 字段；原第一轮记录保留为历史验证事实。

此轮不修改模型运行模块或原测试数据；同步中英文 README 的 919 项测试计数，并重新打包 wheel 的说明元数据。新增根目录 `.gitattributes`，覆盖 `.github/workflows/tests.yml`、`scripts/validate_v0160.py`、`tests/test_ci_portability.py`、本说明、上传指南、验证记录及 SHA256 清单；同时同步 CHANGELOG、中英文 README 和 wheel 内的说明。上传后仍须由原生远程 Windows/macOS 新一轮 Actions 确认完整矩阵成功。
