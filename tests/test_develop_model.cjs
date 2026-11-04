const {test}=require('node:test');const a=require('node:assert/strict');const M=require('../static/develop_model');
test('rotation and reflection keep crop geometry reversible',()=>{
 const p={rotate:0,flip:'none',level_angle:.5,crop_rect:[.125,.25,.625,.875],wb_point:[.125,.75]};
 for(const rotation of [0,90,180,270])for(const flip of ['none','h','v'])for(const op of ['cw','ccw','h','v']){
  const before={...p,rotate:rotation,flip};const after=M.orient(before,op);const back=M.orient(after,{cw:'ccw',ccw:'cw',h:'h',v:'v'}[op]);
  a.deepEqual(back.crop_rect,before.crop_rect);a.deepEqual(back.wb_point,before.wb_point);a.equal(back.level_angle,before.level_angle);
 }
 a.deepEqual(M.orient(p,'cw').crop_rect,[.125,.125,.75,.625]);
});
test('plain, command and range selection match filmstrip behavior',()=>{
 const p=['a','b','c','d'];a.deepEqual(M.selection(p,['a'],'a','c',false,false),['c']);a.deepEqual(M.selection(p,['a'],'a','c',false,true),['a','c']);a.deepEqual(M.selection(p,['a'],'a','c',true,false),['a','b','c']);a.deepEqual(M.selection(p,['a'],'a','a',false,true),[]);
});
test('only bounded confident per-frame gamma recommendations apply',()=>{
 a.deepEqual(M.gammaPatch({parameter_key:'gamma',recommendation:.85,confidence:'high'}),{gamma:.85});for(const value of [NaN,Infinity,.1,3.1])a.equal(M.gammaPatch({parameter_key:'gamma',recommendation:value,confidence:'high'}),null);a.equal(M.gammaPatch({parameter_key:'gamma',recommendation:1,confidence:'none'}),null);
});
