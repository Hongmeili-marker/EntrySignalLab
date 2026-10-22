# EntrySignalLab：CI 修复版手动上传说明

目标仓库：https://github.com/Hongmeili-marker/EntrySignalLab

解压后打开 EntrySignalLab 文件夹，把里面的内容复制到本地仓库根目录，覆盖同名文件并添加新文件，然后提交并推送。README.md、src、tests、scripts、docs、dist、.github 必须直接位于仓库根目录，不能再套一层目录。保留本地仓库自己的 .git 目录。

完整源码共 212 个文件。务必上传 .github/workflows/tests.yml、.gitignore 和 .gitattributes。新增 scripts/validation_portability.py、tests/test_ci_portability.py、CI_FIX_NOTES_zh.md、docs/ci_portability_validation.json；其他修改文件列于修复说明。

如果只使用 GitHub 网页，可按完整相对路径分批上传修改后的文件。建议使用 GitHub Desktop 复制并查看 Changes，避免漏掉新增的辅助脚本。不要只上传 ZIP。

本包保留姓名、单位、邮箱、公开仓库信息，以及完整示例、测试数据和验收文档。原投稿总包的 publication、evidence、original_release 不需要再复制进软件仓库。旧版本命名的测试和验收记录有回归核验用途，不按版本号删除。

上传后查看新一轮 Actions。当前配置包含一个锁定环境的严格回放任务，以及原有七个兼容性任务。任何任务失败时，错误详情会同时出现在控制台日志和下载附件中。未取得远程成功结果前，使用本包实测说明中的环境范围。

正式版本已发布：https://github.com/Hongmeili-marker/EntrySignalLab/releases/tag/v0.25.0；归档版本 DOI：https://doi.org/10.5281/zenodo.23565682；所有版本 DOI：https://doi.org/10.5281/zenodo.23565681。原始模型论文完整书目和论文投稿声明仍需按实际情况补齐。原数值模型的 14 个运行模块未改动；wheel 仅重新打包同步说明和 DOI 元数据。原冻结发行的历史收据不代表本次修改后的整包字节。

第二轮修复增量包仅包含本次改变的文件，供已上传第一轮修复的仓库使用；保持相对路径覆盖同名文件，并新增根目录 .gitattributes。此文件强制 Git 检出文本为 LF，避免 Windows 自动转换换行符破坏原始数据哈希。

DOI 回填增量包只包含本次修改的文件，请按相对路径覆盖 main 分支中的同名文件。已发布的 v0.25.0 标签与 Zenodo 归档保持原样，本次修改不追溯改写已归档文件。
