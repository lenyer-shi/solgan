水质三维荧光光谱指纹工具 - PyQt5 GUI
=====================================

文件清单
--------
  eem_fingerprint.py   核心算法 (预处理流水线、特征提取、相似度)
  fingerprint_db.py    SQLite 指纹库
  eem_visualizer.py    matplotlib 嵌入 PyQt5 的可视化组件
  eem_gui.py           主程序 (启动入口)
  requirements.txt     依赖列表
  blank.csv            纯水空白 EEM (示例)
  industrial.csv       工业废水样本 EEM (示例)

环境准备
--------
  Python 3.8+
  pip install -r requirements.txt

启动
----
  python eem_gui.py

界面分为 4 个 Tab:

[1] 数据加载与预处理
    - 选择 blank CSV 与 sample CSV
    - 调整预处理参数:
        * 通道聚合方法 (median / hampel / tmean / mean)
          —— 用于抑制同 Ex 多次测量因水质波动产生的差异
        * Em 截取范围、Ex 上限
        * 瑞利/拉曼散射屏蔽带宽
        * Savitzky-Golay 窗口与多项式阶
    - 点击 "运行预处理 + 特征提取"
    - 右侧切换查看: 等高线图 / 伪彩图 / 原始 EEM / FRI 占比柱状图
    - 下方表格: FRI 五区, 主荧光峰, 统计描述子

[2] 指纹库管理
    - 打开/新建 .sqlite 文件作为指纹库
    - 点 "+ 入库 (当前样本)" 把 Tab1 当前样本的指纹存入库
      (会询问名称、类别、备注)
    - 选中行可: 删除、查看 EEM
    - 多个项目可同时选中删除

[3] 指纹检索
    - 用 Tab1 当前样本作为查询向量
    - 设置 Top-K, 余弦/欧式权重比 (默认 0.6 / 0.4)
    - 点击 "用当前样本检索" 即可在库中按综合评分排序
    - 选中结果行下方显示 Query 与候选指纹的并排等高线图

[4] 双样本比对
    - 各自选择 A、B 两组的 blank + sample
    - 点 "计算两样本相似度" 输出:
        * 余弦相似度 (Cosine Similarity)
        * 归一化欧式距离 (Euclidean Distance)
        * 综合评分 (0.6 cos + 0.4 (1 - eucl/2))
    - 下方并排显示两样本校正后的 EEM 等高线图

水质波动抑制要点
----------------
设备在同一 Ex 上做了 2 个通道 (255×2, 265×2, 660×2, 700×2),其荧光强度
因水流/温度/微小污染物波动会有差异。本工具默认 "median" 通道聚合法在
逐 Em 维度上取中位数,对个别尖峰最稳健;若数据本身比较干净可切换为
"tmean" 或 "mean" 以降低噪声。所有处理后的指纹向量会进入指纹库统一
管理,确保检索时不被原始波动干扰。

CLI 模式
--------
不需要 GUI 时仍可命令行使用 (生成报告/JSON):
  python eem_fingerprint.py --blank blank.csv --sample industrial.csv \
         --outdir ./report
