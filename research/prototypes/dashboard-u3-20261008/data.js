export const PROJECTS = {alpha:{name:'采购协同',tag:'经营 · 示例 A',code:'CG'},beta:{name:'展陈筹备',tag:'项目 · 示例 B',code:'ZC'}};
export const CRITERIA={1:['比较三家供应商的含税报价与交付周期。','资料覆盖两个年度，注明来源与缺失项。','输出比较表及推荐理由，提供可核对文件。'],2:['比较三家供应商的含税报价与交付周期。','资料覆盖三个年度；缺失年度须补齐，禁止推断数据。','输出比较表、风险说明与推荐理由，文件与本次结果准确关联。']};
export const TASKS=[
 {id:'t1',project:'alpha',title:'供应商比较与采购建议',code:'CG-012',state:'todo',due:'10月12日',owner:'我',criteria:2,source:'决策 D-03 · 采用版本 2',failedAttempts:['E1 · 资料下载失败，无正式结果'],results:[
 {id:'r1',revision:1,status:'not_accepted',time:'10月06日 09:20',attempt:'人工提交 · M1',summary:'初稿已完成，报价未统一含税口径。',files:['comparison'],note:'未接受：口径不一致'},
 {id:'r2',revision:1,status:'pending',time:'10月07日 14:30',attempt:'执行尝试 E2',summary:'比较表已统一含税；按旧要求覆盖两个年度，缺少第三年度。',files:['comparison','report'],note:'旧要求提交，接受将被拒绝'},
 {id:'r3',revision:2,status:'pending',time:'10月08日 10:15',attempt:'人工提交 · M3',summary:'三家供应商、三个年度资料已补齐；推荐乙供应商，风险与来源单列。',files:['comparison','report','image','pdf'],note:'当前要求 v2'}]},
 {id:'t2',project:'alpha',title:'核对九月采购金额与凭据',code:'CG-013',state:'doing',due:'10月10日',owner:'财务智能体',criteria:2,results:[{id:'r4',revision:2,status:'pending',time:'10月08日 09:40',attempt:'执行尝试 E4',summary:'九月含税采购金额已核对，差异项另列。',files:['comparison']}]},
 {id:'t3',project:'alpha',title:'补齐供应商乙第三年度来源',code:'CG-014',state:'blocked',due:'10月09日',owner:'资料智能体',criteria:2,results:[]},
 {id:'t4',project:'alpha',title:'更新月度采购台账',code:'CG-015',state:'doing',due:'10月11日',owner:'采购智能体',criteria:2,results:[]},
 {id:'t5',project:'alpha',title:'确定采购资料口径',code:'CG-009',state:'done',due:'已完成',owner:'我',criteria:1,results:[]},
 {id:'t6',project:'alpha',title:'归档供应商报价',code:'CG-010',state:'done',due:'已完成',owner:'我',criteria:1,results:[]},
 {id:'t7',project:'alpha',title:'整理下一轮议价问题',code:'CG-016',state:'todo',due:'10月14日',owner:'我',criteria:2,results:[]},
 {id:'t8',project:'alpha',title:'重复采购调查',code:'CG-008',state:'cancelled',due:'已取消',owner:'我',criteria:1,results:[]},
 {id:'b1',project:'beta',title:'供应商比较与采购建议',code:'ZC-004',source:'人工独立事项 · 无治理来源',state:'todo',due:'10月15日',owner:'我',criteria:2,results:[{id:'b-r1',revision:2,status:'pending',time:'10月08日 10:20',attempt:'人工提交 · B1',summary:'展陈物料供应商对照已完成；属于示例 B 的独立工作。',files:['report']}]}
];
export const QUESTIONS=[{id:'q1',project:'beta',title:'物料报价是否包含运输费用？',stage:'needs_answer',read:true,handler:'我',attempt:'展陈执行 B2',answer:''},{id:'q2',project:'beta',title:'补充展厅尺寸后等待执行方恢复',stage:'answered_unresumed',read:true,handler:'展陈智能体',attempt:'展陈执行 B3',answer:'按 12 × 18 米的合成场地继续。'}];
export const FILES={
 comparison:{name:'供应商比较.md',type:'md',size:'2.4 KB',text:'# 供应商比较\n\n合成文件 · 当前 R3 示例（非历史文件存储证明）\n\n|供应商|含税报价|周期|\n|---|---:|---|\n|甲|120,000 元|18 天|\n|乙|108,000 元|15 天|\n|丙|116,000 元|21 天|\n\n三个年度资料已标注来源。推荐乙；该结论只用于原型操作。'},
 report:{name:'推荐与风险说明.md',type:'md',size:'3.1 KB',text:'# 推荐与风险说明\n\n合成数据：乙供应商报价较低且周期较短。\n\n## 核对条件\n- 含税口径一致\n- 三个年度资料齐备\n- 来源与风险可核对\n\n## 风险\n供应商乙旺季交付存在排期风险，建议保留甲为备选。\n\n'+Array.from({length:12},(_,i)=>`### 来源条目 ${i+1}\n明确标注的合成来源，用于长文对照及滚动验证。\n`).join('\n')},
 image:{name:'报价对照.svg',type:'image',size:'1.2 KB',url:'samples/comparison.svg'},
 pdf:{name:'采购核对册.pdf',type:'pdf',size:'12 页',url:'samples/checklist.pdf'}
};
export const STATE_LABELS={todo:'待办',doing:'进行中',blocked:'受阻',done:'已完成',cancelled:'已取消',pending:'待验收',accepted:'已接受',not_accepted:'未接受',needs_answer:'待我答复',answered_unresumed:'已答复 · 未恢复'};
export const DEFAULT_STATE={drafts:{},reviews:{},read:{},answers:{},taskStates:{},businessPeriod:'09',filter:'all',scenario:'normal',theme:'light',full:false,events:[]};
