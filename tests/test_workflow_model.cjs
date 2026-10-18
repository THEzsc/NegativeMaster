const test=require('node:test');
const assert=require('node:assert/strict');
const M=require('../static/workflow_model.js');

test('tone styles preserve frame geometry, gamma, color sampling and exposure',()=>{
  const frame={P:{gamma:1.73,nd_gamma:2.4,rotate:90,exposure:-1.2,temp:18,wb_rect:{x0:.1,y0:.1,x1:.2,y1:.2}},cropN:{x0:.2,y0:.2,x1:.9,y1:.8}};
  const before=JSON.stringify(frame);
  for(const key of Object.keys(M.looks)){
    const next=M.patchTone(frame,key);
    for(const field of Object.keys(frame.P))assert.deepEqual(next.P[field],frame.P[field]);
    assert.deepEqual(next.cropN,frame.cropN);
    assert.notEqual(next.P,frame.P);
  }
  assert.equal(JSON.stringify(frame),before);
});
test('uncertain, non-finite and out of engine bounds suggestions cannot apply',()=>{
  for(const recommendation of [null,NaN,Infinity,-1,4])assert.equal(M.canApply({recommendation,parameter_key:'gamma',confidence:'high'}),false);
  assert.equal(M.canApply({recommendation:2,parameter_key:'gamma',confidence:'none'}),false);
  assert.equal(M.canApply({recommendation:4,parameter_key:'nd_gamma',confidence:'medium'}),true);
  assert.equal(M.canApply({recommendation:2,parameter_key:'other',confidence:'high'}),false);
});
test('roll scopes honor explicit selection and visible rows without duplicate paths',()=>{
  const rows=[{path:'a',visible:true,checked:false},{path:'b',visible:false,checked:true},{path:'c',visible:true,checked:false}];
  assert.deepEqual(M.selection(rows,'z'),['b']);
  rows[1].checked=false;assert.deepEqual(M.selection(rows,'z'),['a','c']);
  assert.deepEqual(M.selection([],'z'),['z']);assert.deepEqual(M.selection([],null),[]);
});
