# Requirement: 应用场景与发展方向

本文档基于项目当前状态（Phase 0, ~10%）和 [roadmap.md](roadmap.md) 中的技术路线，结合 2026 年开源生态空缺与行业趋势，梳理项目可能的应用场景、目标需求和战略发展路径。

## 项目核心定位

RISC-V Linux 构建工具链，正在向 **最小化、现代化、安全优先** 的 RISC-V Linux 发行版演进。

| Feature          | Description                                           |
| ---------------- | ----------------------------------------------------- |
| Arch             | RISC-V Dual Architecture (RV32 / RV64)                |
| Runtime          | musl + dinit + btrfs Immutable Root FS                |
| Security         | Landlock / seccomp-bpf / dm-verity enabled by default |
| Build System     | TOML Declarative Configuration, Reproducible Builds   |
| Current Progress | Phase 0 (Build System Modernization), ~10%            |

## 一、应用场景（按优先级排序）

### 1. RISC-V 安全物联网网关操作系统 ⭐ 首选方向 | **优先级：🔴 最高**

#### 1.1 背景与驱动力

- **EU Cyber Resilience Act (CRA)**：2024 年通过，2027 年强制执行，要求所有联网设备
  具备安全更新、SBOM（软件物料清单）、漏洞披露机制。
- **美国 EO 14028**：要求联邦供应链软件提供 SBOM。
- **中国《网络安全审查办法》**：对关键基础设施设备提出类似安全要求。
- 物联网设备数量持续爆发，安全事件频发，合规压力骤增。

#### 1.2 开源空缺

| Existing Solution | Shortcomings                                                                     |
| ----------------- | -------------------------------------------------------------------------------- |
| OpenWrt           | Supports RISC-V, but security model is weak (writable root FS, no dm-verity)     |
| Yocto/Buildroot   | Build system rather than distribution, security integration requires user effort |
| Zephyr / RIOT     | Only suitable for MCU-level devices, not Linux                                   |

**核心空缺**：没有任何现成的 RISC-V 安全物联网 Linux 发行版同时满足——
不可变根文件系统 + 原子更新 + Landlock/seccomp 默认策略 + A/B 分区回滚。

#### 1.3 项目适配度：★★★★★

项目已规划的不可变根 + dm-verity + seccomp-bpf + A/B 更新 + 声明式配置，
恰好覆盖 CRA 合规所需的全部技术栈，与现有 roadmap 高度重合。

#### 1.4 需求清单

| #     | Requirement                                                         | Corresponding Roadmap | New/Existing |
| ----- | ------------------------------------------------------------------- | --------------------- | ------------ |
| R1.1  | Immutable read-only root filesystem                                 | Phase 1.3             | Existing     |
| R1.2  | A/B partition atomic updates + automatic rollback                   | Phase 1.5             | Existing     |
| R1.3  | dm-verity integrity-verified boot chain                             | Phase 4.1             | Existing     |
| R1.4  | Per-service seccomp-bpf syscall whitelist                           | Phase 4.2             | Existing     |
| R1.5  | Per-service Landlock filesystem isolation                           | Phase 4.3             | Existing     |
| R1.6  | Automatic SBOM generation (SPDX / CycloneDX)                        | —                     | **New**      |
| R1.7  | VEX (Vulnerability Exploitability Exchange) integration             | —                     | **New**      |
| R1.8  | Firmware signature verification + secure OTA channel                | —                     | **New**      |
| R1.9  | CRA compliance reference architecture document                      | —                     | **New**      |
| R1.10 | IoT gateway specific configuration preset (`iot-gateway-rv64.toml`) | —                     | **New**      |

#### 1.5 推荐理由

1. **市场窗口紧迫**：EU CRA 2027 年强制执行，设备厂商现在就需要合规方案。
2. **技术路径最短**：与现有 roadmap 高度重合，无需大规模偏移。
3. **差异化最强**：没有现有 RISC-V OS 同时具备上述安全特性。
4. **商业化路径清晰**：开源 OS + 商业合规咨询/认证服务。
5. **社区吸引力**：安全 + RISC-V 双重热点，容易吸引贡献者。

### 2. RISC-V 边缘 AI 推理平台 | **优先级：🟡 高**

#### 2.1 背景与驱动力

- RISC-V Vector Extension (RVV 1.0) 已在主线 Linux 内核稳定支持。
- 大量 RISC-V + NPU 芯片出货：Kendryte K230、Sipeed LM4A (TH1520)、SpaceMIT K1。
- 边缘 AI 推理需求爆发（端侧大模型、视觉检测、语音识别）。
- NVIDIA Jetson 生态硬件锁定严重，开源替代需求强烈。

#### 2.2 开源空缺

- 没有轻量级、安全加固的 RISC-V Linux 发行版专门优化 AI 推理。
- 现有方案（Ubuntu / Debian for RISC-V）体积庞大、启动慢。
- NPU 驱动/运行时（NNAPI / TFLite / ONNX Runtime）在 RISC-V 上缺乏参考集成。

#### 2.3 项目适配度：★★★★☆

#### 2.4 需求清单

| #    | Requirement                                | Corresponding Roadmap | New/Existing |
| ---- | ------------------------------------------ | --------------------- | ------------ |
| R2.1 | RVV Kernel 配置 profile                    | —                     | **New**      |
| R2.2 | NPU 驱动框架集成（内核模块 + 用户空间）    | Phase 2.4 (模块基础)  | **Existing** |
| R2.3 | 容器化推理环境 (crun)                      | Phase 4.4             | **Existing** |
| R2.4 | 模型部署管道 (OCI artifact)                | —                     | **New**      |
| R2.5 | 边缘 AI 专用配置预设 (`edge-ai-rv64.toml`) | —                     | **New**      |

### 3. RISC-V 机密计算 / 可信执行环境 (TEE) 基础 OS | **优先级：🟡 高**

#### 3.1 背景与驱动力

- RISC-V CoVE (Confidential VM Extension) 规范发展中。
- Keystone Enclave（MIT / UC Berkeley）为 RISC-V 提供 TEE。
- Penglai Enclave（中科院 / 蚂蚁集团）是另一个重要的 RISC-V TEE 实现。
- 数据隐私法规趋严（GDPR、中国数据安全法），机密计算是合规关键路径。

#### 3.2 开源空缺

- **没有任何 RISC-V Linux 发行版原生集成机密计算支持。**
- x86 有 Azure Confidential Computing / Enarx，ARM 有 OP-TEE，RISC-V 领域完全空白。
- Keystone 仅提供 SDK 和 demo，缺少完整 host OS 集成。

#### 3.3 项目适配度：★★★☆☆

#### 3.4 需求清单

| #    | 需求                                 | 对应 Roadmap | 新增/已有 |
| ---- | ------------------------------------ | ------------ | --------- |
| R3.1 | Keystone / Penglai 内核模块集成      | —            | **新增**  |
| R3.2 | 安全启动链 (measured boot)           | Phase 4.1    | 扩展      |
| R3.3 | Enclave 生命周期管理 (dinit service) | Phase 2.1    | 扩展      |
| R3.4 | Remote attestation 基础设施          | —            | **新增**  |

### 4. RISC-V 教育与科研实验平台 | **优先级：🟠 中**

#### 4.1 背景与驱动力

- 全球高校 RISC-V 教学快速增长（MIT、UCB、清华、中科大等）。
- 现有教学 OS（xv6-riscv）到生产 Linux 之间存在巨大鸿沟。
- 教育部 / NSF 等推动开源芯片和开源 OS 教学。

#### 4.2 开源空缺

| 现有方案           | 缺陷                                 |
| ------------------ | ------------------------------------ |
| xv6-riscv          | 教学目的，过于简化，无法运行实际应用 |
| Debian / Ubuntu RV | 过于复杂，学生无法理解系统全貌       |

**核心空缺**：缺少一个可以从零构建、理解每个组件的 **现代 RISC-V Linux 参考实现**。

#### 4.3 项目适配度：★★★★★

项目的分层构建路径天然适合教学：
`tiny_shell` -> busybox -> dinit -> 完整系统，每一步可单独理解和实验。

#### 4.4 需求清单

| #    | 需求                                         | 对应 Roadmap | 新增/已有 |
| ---- | -------------------------------------------- | ------------ | --------- |
| R4.1 | 面向教学的逐层文档系列                       | Phase 5.3    | 扩展      |
| R4.2 | 实验 Lab 系列（内核模块、seccomp、Landlock） | —            | **新增**  |
| R4.3 | Spike 模拟器支持（无硬件课堂环境）           | 已有         | 已有      |
| R4.4 | 渐进式构建路径文档                           | —            | **新增**  |

### 5. RISC-V 汽车电子 / 软件定义汽车 (SDV) Zone Controller OS | **优先级：🟠 中**

#### 5.1 背景与驱动力

- 汽车行业正从分布式 ECU 转向 zonal architecture（区域控制器）。
- Bosch、Continental 等已发布 RISC-V 汽车芯片路线图。
- ISO 21434（汽车网络安全）和 UN R155/R156（软件更新）对 OTA 和安全启动有强制要求。
- AUTOSAR Adaptive 需要 Linux 宿主系统。

#### 5.2 开源空缺

- AGL (Automotive Grade Linux) 基于 Yocto/glibc，重量级且 RISC-V 支持有限。
- 没有轻量级、安全加固、面向 RISC-V 的汽车 Linux 平台。

#### 5.3 项目适配度：★★★☆☆

#### 5.4 需求清单

| #    | 需求                                  | 对应 Roadmap | 新增/已有 |
| ---- | ------------------------------------- | ------------ | --------- |
| R5.1 | PREEMPT_RT 内核 profile（确定性调度） | —            | **新增**  |
| R5.2 | SocketCAN / LIN 总线驱动支持          | —            | **新增**  |
| R5.3 | ISO 21434 安全启动链                  | Phase 4.1    | 扩展      |
| R5.4 | OTA 合规更新（A/B + 签名 + 回滚）     | Phase 1.5    | 已有      |

## 二、开源空缺矩阵

| 领域                    | 现有开源方案               | 空缺                           | 本项目填补能力 |
| ----------------------- | -------------------------- | ------------------------------ | -------------- |
| RISC-V 安全 IoT 网关 OS | 无 (OpenWrt 安全不足)      | 不可变根 + 原子更新 + CRA 合规 | ★★★★★          |
| RISC-V 边缘 AI 推理 OS  | 无专用轻量方案             | 安全 + 轻量 + NPU 集成         | ★★★★☆          |
| RISC-V 机密计算 Host OS | 完全空白                   | TEE 集成 + 安全启动链          | ★★★☆☆          |
| RISC-V 教学参考实现     | xv6 (太简) / Ubuntu (太复) | 从零构建的现代 Linux 参考      | ★★★★★          |
| RISC-V 汽车 Zone Ctrl   | AGL (太重, RISC-V 弱)      | 轻量安全 + OTA + 实时          | ★★★☆☆          |
| 可复现 SBOM Linux 构建  | 无完整参考实现             | 声明式构建 + SBOM 生成 + 签名  | ★★★★☆          |

## 三、战略发展路径

```
               当前 (Phase 0, ~10%)
                    │
               Phase 0-1: 打基础
               (musl + disk image + 不可变根)
                    │
         ┌──────────┼──────────┐
         │          │          │
    方向 A:       方向 B:     方向 C:
 安全 IoT 网关  边缘 AI 推理  教育平台
  (CRA 合规)    (RVV+NPU)   (教学文档)
         │          │          │
         └──────────┼──────────┘
                    │
               Phase 4-5
         安全加固 + 真实硬件
                    │
               长期愿景:
      RISC-V 安全计算基础设施 OS
    (覆盖 IoT / Edge / TEE / Automotive)
```

### 推荐首选方向：安全 IoT 网关 OS（方向 A）

| Dimension         | Evaluation                                                                       |
| ----------------- | -------------------------------------------------------------------------------- |
| Market Window     | Urgent — EU CRA enforcement by 2027                                              |
| Technical Path    | Shortest — Highly aligned with existing roadmap                                  |
| Differentiation   | Strongest — No existing RISC-V OS has all security features                      |
| Commercialization | Clear — Open source OS + commercial compliance consulting/certification services |
| Community Appeal  | High — Security + RISC-V dual hotspots                                           |

## 四、近期可执行步骤

以下步骤可在现有 roadmap Phase 0–1 期间并行推进：

| #   | 步骤                             | 依赖           | 产出                             |
| --- | -------------------------------- | -------------- | -------------------------------- |
| S1  | 构建系统集成 SBOM 生成           | Phase 0        | `make sbom` -> SPDX JSON 输出     |
| S2  | 创建 IoT 网关配置预设            | Phase 1.9      | `configs/iot-gateway-rv64.toml`  |
| S3  | CI 流水线添加安全扫描门控        | Phase 0.4      | CVE 扫描 + 固件签名验证          |
| S4  | 发布 CRA 合规参考架构文档        | Phase 1 完成后 | `docs/cra-compliance.md`         |
| S5  | 编写教学系列文档第一篇           | 现在           | `docs/tutorial-01-boot-chain.md` |
| S6  | 创建边缘 AI 配置预设（RVV 启用） | Phase 1        | `configs/edge-ai-rv64.toml`      |

## 附录：需求汇总（全场景）

| ID    | 需求                              | 场景     | 优先级 | 状态   |
| ----- | --------------------------------- | -------- | ------ | ------ |
| R1.1  | 不可变只读根文件系统              | IoT 网关 | 🔴      | 已规划 |
| R1.2  | A/B 分区原子更新 + 自动回滚       | IoT 网关 | 🔴      | 已规划 |
| R1.3  | dm-verity 完整性验证启动链        | IoT 网关 | 🔴      | 已规划 |
| R1.4  | 每服务 seccomp-bpf 系统调用白名单 | IoT 网关 | 🔴      | 已规划 |
| R1.5  | 每服务 Landlock 文件系统隔离      | IoT 网关 | 🔴      | 已规划 |
| R1.6  | 自动 SBOM 生成 (SPDX / CycloneDX) | IoT 网关 | 🟡      | 新增   |
| R1.7  | VEX 集成                          | IoT 网关 | 🟡      | 新增   |
| R1.8  | 固件签名验证 + 安全 OTA 通道      | IoT 网关 | 🔴      | 新增   |
| R1.9  | CRA 合规参考架构文档              | IoT 网关 | 🟡      | 新增   |
| R1.10 | IoT 网关专用配置预设              | IoT 网关 | 🟠      | 新增   |
| R2.1  | RVV 内核配置 profile              | 边缘 AI  | 🟡      | 新增   |
| R2.2  | NPU 驱动框架集成                  | 边缘 AI  | 🟡      | 新增   |
| R2.3  | 容器化推理环境 (crun)             | 边缘 AI  | 🟡      | 已规划 |
| R2.4  | 模型部署管道 (OCI artifact)       | 边缘 AI  | 🟠      | 新增   |
| R2.5  | 边缘 AI 专用配置预设              | 边缘 AI  | 🟠      | 新增   |
| R3.1  | Keystone / Penglai 内核模块集成   | 机密计算 | 🟠      | 新增   |
| R3.2  | 安全启动链 (measured boot)        | 机密计算 | 🟡      | 扩展   |
| R3.3  | Enclave 生命周期管理              | 机密计算 | 🟠      | 新增   |
| R3.4  | Remote attestation 基础设施       | 机密计算 | 🟠      | 新增   |
| R4.1  | 面向教学的逐层文档系列            | 教育平台 | 🟡      | 扩展   |
| R4.2  | 实验 Lab 系列                     | 教育平台 | 🟠      | 新增   |
| R4.3  | Spike 模拟器支持                  | 教育平台 | —      | 已有   |
| R4.4  | 渐进式构建路径文档                | 教育平台 | 🟠      | 新增   |
| R5.1  | PREEMPT_RT 内核 profile           | 汽车电子 | 🟠      | 新增   |
| R5.2  | SocketCAN / LIN 总线驱动支持      | 汽车电子 | 🟠      | 新增   |
| R5.3  | ISO 21434 安全启动链              | 汽车电子 | 🟠      | 扩展   |
| R5.4  | OTA 合规更新                      | 汽车电子 | 🟡      | 已规划 |
