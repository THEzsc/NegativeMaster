/* Small deterministic operations shared by the UI and regression tests. */
(function(root) {
  const looks = {
    neutral: {name:'自然中性', note:'平直对比，保留色彩关系，适合继续精调。', values:{contrast:0,saturation:1,highlights:0,shadows:0,whites:0,blacks:0,vibrance:0}},
    soft: {name:'柔和人像', note:'压低反差、轻收高光，肤色饱和度更克制。', values:{contrast:-.08,saturation:.92,highlights:-18,shadows:12,whites:-6,blacks:3,vibrance:3}},
    rich: {name:'浓郁反差', note:'更深的暗部与更鲜明的色彩，适合日光与街拍。', values:{contrast:.18,saturation:1.08,highlights:-8,shadows:-5,whites:5,blacks:-10,vibrance:12}},
    open: {name:'通透宽容', note:'打开阴影并柔化高光，适合大光比画面。', values:{contrast:.02,saturation:1,highlights:-30,shadows:28,whites:-8,blacks:-3,vibrance:6}},
    matte: {name:'柔灰印相', note:'抬起黑位、降低饱和度，保留柔和的印相感。', values:{contrast:-.04,saturation:.88,highlights:-12,shadows:8,whites:-8,blacks:20,vibrance:-5}}
  };
  function canApply(report) {
    if(!report || !Number.isFinite(report.recommendation)) return false;
    const bounds=report.parameter_key==='nd_gamma'?[1,8]:report.parameter_key==='gamma'?[.6,3]:null;
    return !!bounds && report.confidence!=='none' && report.recommendation>=bounds[0] && report.recommendation<=bounds[1];
  }
  function patchTone(settings, look) {
    return {...settings, P:{...settings.P,...looks[look].values}};
  }
  function selection(rows, current) {
    const checked=rows.filter(r=>r.checked);
    const scope=checked.length?checked:rows.filter(r=>r.visible);
    return [...new Set(scope.length?scope.map(r=>r.path):(current?[current]:[]))];
  }
  const api={looks,canApply,patchTone,selection};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.NMWorkflowModel=api;
})(typeof globalThis!=='undefined'?globalThis:this);
