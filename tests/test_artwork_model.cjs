const test=require('node:test');
const assert=require('node:assert/strict');
const model=require('../static/artwork_model.js');
const data=require('../data/film_artwork.json');
test('Chinese brand aliases and exact film identity find offline assets',()=>{
  const gold=model.filter(data.artworks,{query:'柯达 GOLD 200'});
  assert.ok(gold.length);assert.ok(gold.every(a=>a.stock_ids.includes('kodak-gold-200')));
  const matched=model.filter(data.artworks,{matched:true,stockId:'kodak-portra-160',format:'135'});
  assert.ok(matched.length);assert.ok(matched.every(a=>a.name==='PORTRA 160'));
  assert.equal(model.filter(data.artworks,{matched:true,stockId:'kodak-portra-160',format:'120'}).length,0);
  assert.equal(model.filter(data.artworks,{matched:true,stockId:''}).length,0);
});
test('packaging references include Phoenix versions without conflating their models',()=>{
  const result=model.filter(data.references,{query:'凤凰'});assert.ok(result.length);
  const second=model.filter(data.references,{matched:true,stockId:'harman-phoenix-ii'});
  assert.ok(second.length);assert.ok(second.every(a=>a.name.toLowerCase().includes('ii')));
  assert.ok(result.some(a=>!a.stock_ids.includes('harman-phoenix-ii')));
});
