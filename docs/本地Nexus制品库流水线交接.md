# 本地 Nexus 制品库流水线 — 交接文档

> 交接时间：2026-11-25 09:54 ｜ 环境：192.168.7.2（root），仅允许在 `/data/test` 目录操作，全程只用 Docker、不在宿主机装 Maven
> 关联文档：《多仓库模板设计.md》《多仓库依赖缺失清单.md》（阿里云口径的扫描清单）、`config/missing-deps.csv`

## 一、背景与目标

- 各服务迭代时，上游 facade/framework 制品需要**手动上传并同步版本号**才能单个发版 → 目标是搭一套本地制品仓库流水线：**构建成功自动上传制品 → 下游从私服拉取 → 全程脱离阿里云**。
- 本阶段在测试服务器上完成了：Nexus 部署、历史构件迁移、自动上传/拉取闭环验证、以及 19 个仓库的**脱离阿里云全量编译打包**。

## 二、环境与目录布局（192.168.7.2:/data/test）

| 路径 | 说明 |
|---|---|
| `nexus-data/` | Nexus 3.70.1 数据目录（属主必须 `200:200`） |
| 容器 `nexus` | 本地私服，端口 **18081**，admin 密码 `0e66cad4-7a86-46a2-b5ea-0afa89f2011d` |
| 仓库结构 | `maven-releases`(hosted) / `maven-snapshots`(hosted) / `maven-central`(proxy) / `maven-public`(group，四者聚合) |
| `poms/<repo>/` | 19 个仓库的源码 checkout，构建产物直接落在 `*/target/` |
| `repos.txt` / `repos_meta.tsv` | 仓库清单（19 个，repo/url/lang/服务数）；构建脚本读 `repos_meta.tsv` |
| `.m2/settings.xml` | **构建端唯一配置**：只指向 192.168.7.2:18081；备份在 `.m2/settings.xml.pre-mirror.bak` |
| `m2-final/` | 本地构建共享的 `maven.repo.local`（越跑越快） |
| `m2-aliyun/` + `aliyun-settings.xml` | 历史遗留：用用户提供的阿里云 settings 拉取的缓存，仅作迁移数据源 |
| `build_all_local.sh` / `build_all_local_v2.sh` | 全量构建脚本（v2 从 `repos_meta.tsv` 第 2 行起跑、不清空汇总） |
| `build_local_summary.tsv` | **最终汇总**（每行：repo/退出码/耗时/lang/服务数/分类/首个ERROR） |
| `build_local_summary.first-run.tsv` | 首轮（未补依赖时）汇总留档 |
| `build-local-logs/*.log` | 每仓完整构建日志，`*.retry.log` 为补依赖后的重跑日志 |
| `retry_two_repos.sh`、`fill_nexus.sh`、`analyze_missing2.py` | 补依赖重跑 / 手工 deploy / 缺失坐标分析脚本 |

镜像（本地加速拉取后推到内网 Harbor）：`hub.hzbxhd.com/library/nexus3:3.70.1`、`maven17:3.9`、`maven8:3.9`。

**构建端 settings.xml 关键点**（这是"脱离阿里云"的核心）：
- servers 只有 `nexus-releases` / `nexus-snapshots`（deploy 用），无任何云效凭据；
- 三个 mirror 全部指向 `http://192.168.7.2:18081/repository/maven-public/`：
  1. `external:http:*`（绕过 Maven 3.9 HTTP blocker）；
  2. `central`；
  3. `nexus-pom-repos`：把 19 个 pom 里写死的 7 个外部仓库 id（`nexus-plugin-public`、`nflow-releases/snapshots`、4 个 `packages.aliyun.com` 云效仓库 id）全部镜像到本地 Nexus。
- profile 里补了 `pluginRepositories`（否则插件仍走 pom 写死的外部私服）。

## 三、已完成的验证结论

1. **脱离阿里云 ✅**：19 份全量构建日志中 0 处出现 `packages.aliyun.com` / `nxs.qiangyun.com`，540 次依赖下载全部来自本地 Nexus。
2. **自动上传制品 ✅**：`mvn deploy` / `deploy:deploy-file` 均验证成功——fin-api、sign-api（首轮）、ocr-verify-service-facade `26.11.10.1`、fin-api `release-0311-SNAPSHOT`（本轮）。
3. **干净仓库从私服拉取 ✅**：清空本地仓库后从 18081 拉取构件完成编译（`finapi-pull` / `signapi-pull` 容器，Exited 0）。
4. **性能**：镜像修正前每个依赖先试外部私服超时（6 分钟只解析 ~40 个 pom）；修正后全量 19 仓 **约 6 分钟**跑完（每仓 4~46 秒）。

## 四、全量构建结果（19 仓库）

**12 个 BUILD SUCCESS**，产物在 `poms/<repo>/…/target/`，例如：
`asset-distribution-platform.jar`、`bank-company-connection.jar`、`bill-config.jar`、`bill-customer-channel.jar`、`callcenter-service.jar`、`cash-gio.jar`、`data-enrich.jar`、`fin-batch.jar` + `fin-core-service.jar`、`invoice-service.jar`、`ocr-verify-service.jar`、`post-loan-app.jar`、`sign-service.jar`。

**7 个失败，全部是"缺依赖"**（无编译错误、无超时）：

| 仓库 | 卡住的缺失构件 |
|---|---|
| bill-deduction | `zl.util.security:zl-util-security:3.0.0` |
| bill-repayment | `com.qiangyun.common.util:common-util:1.0.0` |
| bill-rights | `jdd-open-sdk:1.7.3`、`bill-deduction-facade:25.07.08`、`third-party-call:25.09.16.02` |
| bill-service | `bill-rights-facade:26.06.22.2`（首轮缺 ocr-facade，已补并推进到这里） |
| channel-manage | `common-util:23.08.28.01`（首轮缺 fin-api SNAPSHOT，已补并推进到这里） |
| lite-rule-service | `lyx-framework-constants/-core:25.12.02` |
| backend-api (java8) | `com.lq:ruoyi-common-datascope:26.03.09.01` |

## 五、缺失构件清单（12 个坐标，实测口径）

- **已解决（2）**：`ocr-verify-service-facade:26.11.10.1`、`fin-api:release-0311-SNAPSHOT` —— 均为"本地构建出 jar → deploy 到私服 → 下游解析成功"，闭环已验证。
- **本地有同版本 jar、尚未上传（1，中断点）**：`com.luyouxuan.bill.rights:bill-rights-facade:26.06.22.2`，jar 在 `poms/bill-rights/facade/target/`，pom 版本匹配，可直接 deploy。
- **本地无同版本产物、需迁移（9）**：`jdd-open-sdk:1.7.3`、`ruoyi-common-datascope:26.03.09.01`、`lyx-framework-constants:25.12.02`、`lyx-framework-core:25.12.02`、`bill-deduction-facade:25.07.08`、`common-util:1.0.0`、`common-util:23.08.28.01`、`third-party-call:25.09.16.02`、`zl-util-security:3.0.0`。

> 根因是**版本漂移**：下游 pom 写死的是历史版本，私服里普遍只有同名新版本（如 common-util 有 8 个日期版本但没有 1.0.0）。补一个缺失就暴露下一层，属于正常现象。

## 六、后续步骤（按优先级）

1. **收尾中断点**：deploy `bill-rights-facade:26.06.22.2`（命令见 §七），重跑 `bill-service`，观察是否继续暴露下一层。
2. **迁移 9 个历史版本构件**：二选一——
   - 从原制品库（阿里云云效 / 公司 Nexus `nxs.qiangyun.com`）**一次性**拉取后 `deploy:deploy-file` 到本地 Nexus（迁移动作可以碰外部源，构建端仍不碰）；
   - 或统一升级下游 pom 的写死版本到私服已有版本（改业务代码，需业务侧确认）。
3. **流水线落地**（解决"每次迭代手动同步版本号"）：
   - 上游仓构建成功后自动 `mvn deploy -DaltDeploymentRepository=nexus-releases::default::http://192.168.7.2:18081/repository/maven-releases/`（已验证）；
   - 下游版本统一由 BOM / 平台构建参数注入，替代 pom 写死版本；
   - 构建节点只需下发 §二 的 settings.xml，即可保证"只认本地私服"。
4. 可选：把"扫缺失 → 本地有同版本 jar 自动 deploy → 只重跑受影响仓"做成循环脚本（思路已验证，单轮逻辑见 `analyze_missing2.py` + `fill_nexus.sh`）。

## 七、关键命令速查

```bash
# 单仓构建（java17 / java8 换镜像）
docker run -d --name t-x -v /data/test/poms/<repo>:/workspace -v /data/test/m2-final:/m2 \
  -v /data/test/.m2/settings.xml:/settings.xml:ro -w /workspace \
  hub.hzbxhd.com/library/maven17:3.9 \
  mvn -B -U -s /settings.xml -Dmaven.repo.local=/m2 -DskipTests clean package

# 构建成功自动上传制品（流水线核心）
mvn -B -DskipTests clean deploy \
  -DaltDeploymentRepository=nexus-releases::default::http://192.168.7.2:18081/repository/maven-releases/

# 单文件补录私服（jar+pom）
docker run --rm -v /data/test/poms/<repo>:/src -v /data/test/.m2/settings.xml:/settings.xml:ro \
  -v /data/test/m2-final:/m2 hub.hzbxhd.com/library/maven17:3.9 \
  mvn -B -s /settings.xml -Dmaven.repo.local=/m2 deploy:deploy-file \
  -Dfile=/src/<module>/target/<artifact>-<version>.jar -DpomFile=/src/<module>/pom.xml \
  -DrepositoryId=nexus-releases -Durl=http://192.168.7.2:18081/repository/maven-releases/

# 汇总缺失坐标 / 查看结果
grep -hE "Could not find artifact" /data/test/build-local-logs/*.log | sort -u
cat /data/test/build_local_summary.tsv
```

## 八、注意事项

- Nexus 数据目录权限必须 `chown -R 200:200 /data/test/nexus-data`，否则容器起不来。
- `maven-releases` 默认**禁止同版本重复上传**，重传前先用 `curl -I` 确认不存在（SNAPSHOT 可重复上传）。
- `settings.xml` 与本文档含 Nexus 凭据和服务器密码，**不要提交到公共仓库**；服务器密码在会话记录中，交接时线下单独提供。
- 平台侧多仓模板/构建链路代码（`modules/cicd/…multi*`、`CicdConfigPage.js`、`config/multi-repo-template.sample.json`）与本验证相互独立，均已合入当前工程，勿用 Agent 侧 compile-only 思路（已撤回）。
