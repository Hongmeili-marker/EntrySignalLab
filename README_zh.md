# EntrySignalLab 使用说明

当前 v0.25.0：统一强度求解输入，保存实际局部探测记录，并明确提示显示收益与受保护判断的差异。验收见 docs/v0250_acceptance.md；自动生成数量见 docs/api.md。
当前版本 v0.25.0。本软件用于预公告与市场进入时机的科研计算。它支持 RF、RL、DF、DL 四种情景、原文公式核验、约束求解、参数扫描、不确定性分析和图表导出。软件完全本地运行，不需要服务器或 API Key。

## 安装与运行

包声明最低 Python 3.10 并要求兼容依赖；下述命令在 Python 3.12.14 环境实测。锁定依赖需要 Python 3.11 以上。请先创建虚拟环境，在解压的软件目录打开终端：

```sh
python -m pip install .
entrysignal reproduce --config examples/product_launch.json --out results/first_run
entrysignal verify results/first_run
```

打开 `results/first_run/report.html` 查看报告。结果目录同时包含 CSV、JSON、PNG、SVG、PDF 和 manifest.json。重复运行请换一个空目录，软件不会覆盖已有实验。

运行全部示例和基准测试：

```sh
python scripts/reproduce.py --out results/all
python -m unittest discover -s tests -v
```

## 结果的含义

RF 和 DF 情景中，对象平台在时间 0 进入，竞争平台的进入滞后由输入固定。RL 和 DL 情景中，竞争平台在时间 0 进入，对象平台选择滞后。软件比较的是这些条件下的收益，不能将排序称为博弈均衡。

`co_best` 表示四种进入情景中并列最佳的方案；`preferred_with_outside_option` 另行与零收益的不进入参考比较。即使 RL 在进入情景中最佳，如果所有收益均为负，后一个字段也会显示 `no_entry`。

`no_finite_announcement_optimum` 表示当前设定缺少有限的预公告最优解，需要提供强度上限或正的预公告成本。`announcement_nonunique` 表示最优强度可能不唯一。原文公式的六项核验记录与正常计算结果分开保存。

产品发布示例使用人为指定的成本参数，不是实际企业数据。软件和文稿没有预设“RL 总是最优”。作者及支持邮箱已填写；公开仓库为 [https://github.com/Hongmeili-marker/EntrySignalLab](https://github.com/Hongmeili-marker/EntrySignalLab)。正式投稿仍需固定版本发布链接等信息。


## 当前版本和核验范围

软件版本为 0.25.0。原发行的 907 项测试、28 个校验器与 61 组实验均通过本地 Linux 核验。原投稿准备版只调整文档与文稿；本次 CI 修订另行调整测试、验证脚本与工作流；十四个运行模块、依赖锁和示例保持原字节。测试与校验器已增加跨环境科学核验和独立的严格回放模式。本上传包的 wheel 从未改动的运行模块重新构建，以更新作者及公开仓库元数据；原发行的整包哈希与历史收据不代表这次元数据修订。不要安装历史版本的 wheel。

包声明最低 Python 3.10，要求选择兼容依赖；已锁定的科学环境需要 Python 3.11 以上，实际执行版本为 Python 3.12.14。本次 CI 修订已在本地 Linux 实测 Python 3.10 最低依赖、3.12 锁定环境和 3.13 较新依赖；原生 Windows、macOS 和修订后的远程矩阵仍以上传后结果为准。

完整操作见 QUICKSTART.md。局部探测记录不构成全局最优证明。原文完整书目、公开版本链接及官方专用模板核对仍须完成，见 RELEASE_CHECKLIST.md。

## 作者与联系信息

**Hongmei Li**  
School of Medical Information Engineering, Shenyang Medical College, Shenyang, China  
电子邮箱：[Hongmeili@symc.edu.cn](mailto:Hongmeili@symc.edu.cn)

## 跨环境 CI 修复

当前共有 917 项测试，包含原 907 项和 10 项新增的验证策略反例。CI 保留 Windows、macOS、Python 3.12/3.13 及 Python 3.10 最低依赖任务，另设 Linux/Python 3.12 锁定依赖的严格回放任务。跨环境检查允许有明确界限的数值误差，仍严格核验策略、收益符号、零与非零、配置边界及独立积分；不要求排序比较函数的内部调用顺序一致。具体修改和本地实测见 CI_FIX_NOTES_zh.md。远程矩阵的成功状态须以上传后实际 Actions 结果为准。
