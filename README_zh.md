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

软件版本为 0.25.0。原发行的 907 项测试、28 个校验器与 61 组实验均通过本地 Linux 核验。本次投稿准备只调整文档与文稿；十四个运行模块、依赖锁、示例、测试和校验器保持原字节。本上传包的 wheel 从未改动的运行模块重新构建，以更新作者及公开仓库元数据；原发行的整包哈希与历史收据不代表这次元数据修订。不要安装历史版本的 wheel。

包声明最低 Python 3.10，要求选择兼容依赖；已锁定的科学环境需要 Python 3.11 以上，实际执行版本为 Python 3.12.14。最低版本、Windows、macOS 和远程 CI 仍未在本轮实测。

完整操作见 QUICKSTART.md。局部探测记录不构成全局最优证明。原文完整书目、公开版本链接及官方专用模板核对仍须完成，见 RELEASE_CHECKLIST.md。

## 作者与联系信息

**Hongmei Li**  
School of Medical Information Engineering, Shenyang Medical College, Shenyang, China  
电子邮箱：[Hongmeili@symc.edu.cn](mailto:Hongmeili@symc.edu.cn)
