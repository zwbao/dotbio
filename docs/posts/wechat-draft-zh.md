# AI 原生的基因组数据，应该长什么样？

> 微信公众号草稿 · 2026-05-09 · zwbao

最近读到 `@我是建设者` 的「基因组学还没做好拥抱 AI」，谈 VCF 这种 2011 年定的格式不适合 LLM 直接读，The Genome Computer Company 因此推出了 `.genome` 格式。

我同意问题的诊断，但不同意他们的解药。所以把不同的解法写成了代码：

> **github.com/zwbao/dotbio**——Apache 2.0，今天上线 v0.1.0。

## 一、为什么 VCF 不适合 LLM

VCF 是给生信工程师写的。把一份 WGS 文件直接丢给 Claude，问"我能不能吃 clopidogrel？"，它大概率会犯傻。一行典型的 VCF 长这样：

```
chr10  94781859  rs4244285  G  A  100  PASS  DP=30  GT  0/1
```

这一行说了什么？要 LLM 知道这是 CYP2C19 \*2 等位基因、知道 \*2 是 loss-of-function、知道 \*1/\*2 是 IM 表型、知道 IM 表型对 clopidogrel 意味着什么——它得跑一整套外部 pipeline。每一步都掉准确率，每一步都烧 token。

VCF 的问题不是它写错了，而是它的目标读者是生信工程师，不是 LLM。**这是十几年前合理的设计选择，但不是 AI 时代该有的设计。**

## 二、`.genome` 的对与不够

`.genome` 的思路是把这一切提前烤好，写成 LLM 看得懂的 markdown：

```
You are CYP2C19 *1/*2 (Intermediate Metabolizer).
Clopidogrel: consider alternative if ACS/PCI.
```

LLM 直接读结论，不用再推理。**这一步方向是对的。**

但这个设计有三处不够。

**第一，事实和解读被合并到一层。** Markdown 里写了 "you are CYP2C19 \*1/\*2"，但底层那个 rs4244285 G/A 的原始 call 哪去了？已经被吸收进结论里。想重算、想换规则集、想审计——都做不到。文件成了一份不可逆的"熟"数据。

**第二，它是个快照。** ClinVar 每周更新，CPIC 指南每年改。`.genome` 是某个时间点的判断。下周变了，整个文件作废，重烤一遍。"我三个月前的解读说什么来着？"——查不了。

**第三，证据是隐含的。** Markdown 段落写"clopidogrel 不要用"，但凭什么？哪条 guideline？哪个版本？哪条原始 call 推的？读者只能选择信或不信。

这三件事放在一起，本质上是同一件事的三个侧面：

> **`.genome` 把 fact、interpretation、time 三层折叠成了一层 markdown。**

折叠让它变得 LLM-readable，但代价是失去了可重算性、可审计性、和时间维度。

## 三、AI 原生应该意味着什么

第一性原理应当是：**AI 原生的生物数据结构必须把 fact、interpretation、time 三层分开**。

具体三个原则：

> **1. Multi-scale collapsing（多尺度可折叠）**
>
> variant → gene → haplotype → phenotype → clinical decision，不同问题问不同尺度。LLM 读 phenotype 层就够回答用药；要再深就顺哈希链下钻到原始 call。视图按需展开，token 花在它真正问的层级上。

> **2. Evidence chain as data（证据链是数据）**
>
> 每条 claim 强制带上：来自哪些 fact 哈希、用了哪个 ruleset 版本、引用了哪条 guideline、推导路径是什么。不能裸下结论。证据是数据本身，不是脚注。

> **3. Time as dimension（时间是维度）**
>
> facts 是 immutable 的、内容寻址的；解读是 append-only 的 commit log；ref 像 git 一样指向某个 commit。ClinVar 重分类一个变异？追加一个 commit，老 ref 不动。

这三件事其实就是 git 的范式。git 的事实是 blob，历史是 commit，名字是 ref。我做的 `.bio` bundle 不过是把这一套搬到生物数据上：

```
patient.bio/
├── manifest.json
├── facts/<hash>.json              # CAS 层，immutable
├── commits/<timestamp>.commit.json # append-only 解读日志
├── views/{pgx,germline,...}.md    # 物化的"透镜"
└── refs/{HEAD,stable,...}         # 命名指针
```

VCF 是事实层，dotbio 在它上面加一层可携带、可查询、AI-ready 的解读层。它不替代 VCF——它们在不同层。

## 四、三十秒的 demo

```bash
git clone https://github.com/zwbao/dotbio
cd dotbio && pip install -e .

bio compile examples/synthetic/input.vcf -o /tmp/patient.bio
bio show /tmp/patient.bio --view pgx
bio update /tmp/patient.bio --ruleset clinvar@2026-05-08
bio diff /tmp/patient.bio stable HEAD
```

最关键的是最后一条 diff：

```
# Diff  stable → HEAD
- 1 changed (same target, new interpretation)

## Reclassifications

- BRCA1 c.68_69delAG (185delAG)
  - was: likely_pathogenic  (clinvar@2026-05-01)
  - now: pathogenic         (clinvar@2026-05-08)
  - reason: ruleset reclassified likely_pathogenic → pathogenic
```

同一份 VCF，同一个人，解读变了——因为世界对这个变异的理解变了。

dotbio 没改任何旧文件，只追加了一个 commit。老 ref `stable` 还指着上次的判断，新 ref `HEAD` 是这周的判断，diff 只显示真正动过的那一条。

这是 `.genome` 做不到的事，也是把 fact、interpretation、time 三层分开之后自然涌现的能力。

## 五、用数据说话

光讲道理不行。我用 NA12878 真实数据（HapMap CEU 公开样本，临床实验室金标准；从 1000 Genomes 30x panel 抽 8 个 PGx 位点），跑了三组可复现的实验。脚本和原始数据在 [`bench/`](https://github.com/zwbao/dotbio/tree/main/bench)。

**实验 1：初次查询的真实 token 成本**

用 Anthropic 实际使用的 Claude tokenizer（Xenova port）数：

| 格式 | tokens |
|---|---:|
| VCF（仅原始基因型） | 676 |
| VCF + PharmCAT ruleset（LLM 当场做 annotation） | 1,866 |
| `.genome`（按公开示例忠实重建，含 8 个位点） | 663 |
| `.bio`（manifest + pgx view） | 834 |

`.bio` 比 `.genome` 多 26% token——不是数量级差距。**raw token count 不是这两个格式真正分胜负的维度。**

**实验 2：ClinVar 把 BRCA1 LP→P 之后，要读多少 token 才能知道什么变了**

| 格式 | 检测方法 | tokens | 原生时间旅行 |
|---|---|---:|---|
| VCF | 整条 pipeline 重跑 | 1,866 | 否 |
| `.genome` | 重烤整个文件，肉眼对比 | 663 | 否 |
| `.bio` | `bio diff stable HEAD` | **170** | 是 |

`.bio` 比 `.genome` 便宜 **~4×**，比 VCF 便宜 **~11×**。这个优势会随文件增大线性扩大——`.genome` 是 O(N)，`.bio` 是 O(diff)。

**实验 3：LLM 端到端——给一个 fresh Claude agent 同样的问题，禁用所有工具，只能读给它的格式，看它能答出什么**

问题：「NA12878 能不能在标准剂量下安全服用 clopidogrel？」

| 格式 | 表型 | 二倍型 | 引用指南（带版本）| 备注 |
|---|---|---|---|---|
| VCF | unknown | unknown | ❌ | agent 自报"无法回答，需要外部知识"——诚实，但没用 |
| VCF + ruleset | Intermediate Metabolizer | \*1/\*2 | ✓ CPIC@2022 | 能答，但 token 是 .bio 的 2.2× |
| `.genome` | Intermediate Metabolizer | \*1/\*2 | ❌ unknown | **能给表型，丢了 guideline 引用** |
| `.bio` | Intermediate Metabolizer | \*1/\*2 | ✓ CPIC@2022 | 能答 + 带审计链 |

最关键的是 `.genome` 那一行：它说"考虑替代方案"，但没说凭哪条 guideline。LLM 老老实实回答 `guideline_cited: unknown`。`.bio` 因为 evidence chain 是强制的，CPIC@2022 直接在 view 里。

**结论：**

- `.bio` 在初次查询多花约 26% token——这是直接成本
- 换来的是：唯一显式带 guideline 版本号 + 唯一带 4× 更便宜的更新 diff + 唯一原生支持时间旅行
- 这笔账在小 panel 上微薄，在长期使用 + 大 panel 上 asymptotic 优势放大

四个 agent 的原始 JSON 回答、tokenizer 选择、`.genome` 重建的依据全在 [`bench/results/`](https://github.com/zwbao/dotbio/tree/main/bench/results)，可复现可质疑。

附：跑完 `bio compile`，dotbio 给出两条临床真实的判断——**CYP2C19 \*1/\*2 → Intermediate Metabolizer**（clopidogrel CPIC@2022 建议 ACS/PCI 时考虑换药）和 **MTHFR C677T 杂合**（叶酸代谢约降 30%）。都和 NA12878 已发表的 PGx profile 一致。

## 结语

做这件事不是为了产品，而是想立一个判断：

> **AI 原生的生物数据结构应该把「事实 / 解读 / 时间」三层分开，而不是烤成一份 markdown。**

更值得想的不是"基因组"这个具体载体——而是把同样的设计原则应用到病人数据、肿瘤演化、罕见病诊断、临床试验招募……整个生医数据栈。`.bio` 只是个 sketch。

仓库 Apache 2.0，欢迎 issues、PR 和批评。

**第二版总要等第一版被反驳。**

---

> 链接：github.com/zwbao/dotbio
> 致谢：感谢 `@我是建设者` 原文「基因组学还没做好拥抱 AI」提供了思考起点。
