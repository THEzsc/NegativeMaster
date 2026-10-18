'use strict';
(function(root){
  const aliases={'柯达':'kodak','富士':'fujifilm','伊尔福':'ilford','福马':'foma','乐凯':'lucky','凤凰':'phoenix','哈曼':'harman','爱克发':'agfa'};
  function searchKey(value){let result=String(value||'').toLowerCase();for(const [from,to] of Object.entries(aliases))result=result.replaceAll(from,to);return result.replace(/[\s\-–’']/g,'');}
  function filter(items,{query='',brand='',stockId='',format='',matched=false}={}){
    const key=searchKey(query);
    return items.filter(item=>(!brand||item.brand===brand)&&(!matched||!!stockId&&item.stock_ids.includes(stockId)&&(!format||item.format===format))&&(!key||searchKey([item.brand,item.name,item.variant,item.format,item.iso,item.expiry].join(' ')).includes(key)));
  }
  const model={searchKey,filter};
  if(typeof module==='object'&&module.exports)module.exports=model;else root.ArtworkModel=model;
})(typeof window==='undefined'?globalThis:window);
