import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const bundled = new URL("../../android/src/android/app/src/main/assets/nanomuse/public-watches.js", import.meta.url);
const engine = vm.createContext({});
vm.runInContext(readFileSync(bundled, "utf8"), engine);
const now = Date.UTC(2026,4,17,12);
const feed = "https://example.org/feed";
function read(kind,target,responses=[]) {
  return JSON.parse(engine.NanoMusePublicRead(JSON.stringify({kind,target,now,responses})));
}
function step(kind,target,responses,body,check, finalUrl) {
  const { request } = read(kind,target,responses);
  assert.ok(request?.url);
  check?.(new URL(request.url));
  responses.push({url:request.url,finalUrl,body:typeof body==="string" ? body : JSON.stringify(body)});
}
function work(n,at,score=.94,topic="T701") {
  return {id:"https://openalex.org/W"+n, publication_date:at, title:"Public result "+n,type:"article",
    primary_topic:{id:"https://openalex.org/"+topic,display_name:"Topic "+topic,score}};
}

test("canonical identifiers and exact response ordering; a profile is never scraped",() => {
  assert.equal(engine.nmWatchNormalize("research_author","https://orcid.org/0000-0000-0000-001X"),"0000-0000-0000-001X");
  assert.equal(engine.nmWatchNormalize("scholar_profile","https://scholar.google.com/citations?hl=en&user=Abcd1234"),"Abcd1234");
  assert.throws(()=>engine.nmWatchNormalize("research_author","0000-0000-0000-0011"));
  for(const target of ["https://example.org/feed?k=secret","https://localhost/feed","https://example.org/a/../rss"]) {
    assert.throws(()=>engine.nmWatchNormalize("feed",target));
  }
  assert.ok(read("scholar_profile","Abcd1234").error);
  assert.ok(read("github_repo","sample/project",[{url:"https://example.org/",body:"{}"}]).error);
});

test("GitHub public owner search returns recent open issues and checks ownership",() => {
  const resp=[], item={repository_url:"https://api.github.com/repos/Sample/Project",number:8,title:"Printer stopped",state:"open",created_at:"2026-05-16T11:00:00Z"};
  step("github_user","Sample",resp,{incomplete_results:false,items:[item,{...item,pull_request:{}},{...item,created_at:"2020-01-01T00:00:00Z"}]}, url=>{
    assert.equal(url.host,"api.github.com");assert.match(url.searchParams.get("q"),/^user:sample is:issue is:open/);
  });
  assert.deepEqual(read("github_user","Sample",resp).items,[{key:"github:sample/project#8",text:"Open issue sample/project#8 (2026-05-16): Printer stopped",url:"https://github.com/sample/project/issues/8"}]);
  resp[0].body=JSON.stringify({incomplete_results:true,items:[]});assert.ok(read("github_user","sample",resp).error);
  resp[0].body=JSON.stringify({incomplete_results:false,items:[{...item,repository_url:"https://api.github.com/repos/other/project"}]});
  assert.ok(read("github_user","sample",resp).error);
});

test("research author checks publications, actual citations and corroborated high-confidence topic",()=>{
 const resp=[], k="research_author", t="A123";
 step(k,t,resp,{results:[work(1,"2026-04-01"),work(2,"2026-03-01"),work(3,"2025-01-01"),work(4,"2024-01-01")]},
  u=>assert.match(u.searchParams.get("filter"),/^authorships.author.id:A123,/));
 step(k,t,resp,{results:[work(8,"2026-05-16"),work(9,"2026-05-16",.1),work(10,"2026-01-01")]},
  u=>assert.match(u.searchParams.get("filter"),/^primary_topic.id:T701,authorships.author.id:!A123,/));
 step(k,t,resp,{results:[work(11,"2026-05-12")]},u=>assert.match(u.searchParams.get("filter"),/^cites:W1\|W2\|W3\|W4,/));
 const rows=read(k,t,resp).items;
 assert.deepEqual(rows.map(r=>r.key),["openalex:W1","openalex:W2","openalex:W11","openalex:W8"]);
 assert.match(rows[3].text,/Related research/);
});

test("missing strong repeated interests skips related lookup; DOI and topic queries are bounded",()=>{
 const resp=[];
 step("research_author","A123",resp,{results:[work(1,"2026-05-01"),work(2,"2026-05-01")]});
 assert.match(decodeURIComponent(read("research_author","A123",resp).request.url),/cites:W1\|W2,/);
 const doi=[];
 step("research_work","10.1234/one",doi,{id:"https://openalex.org/W35",doi:"https://doi.org/10.1234/one"});
 step("research_work","10.1234/one",doi,{results:[work(51,"2026-05-01")]},u=>assert.match(u.searchParams.get("filter"),/^cites:W35,/));
 assert.match(read("research_work","10.1234/one",doi).items[0].text,/Paper citing DOI/);
 const req=read("research_topic","quantum optics").request;
 assert.equal(new URL(req.url).searchParams.get("search"),'"quantum optics"');
});

test("RSS IDs survive edits, dates filter old results, XML rejects partial documents",()=>{
 const xml='<rss><channel><item><guid>id:1</guid><title>Field guide 更新</title><link>/articles/first</link></item><item><guid>id:1</guid><title>Duplicate</title></item><item><title>Archived</title><pubDate>2020-01-01</pubDate></item></channel></rss>';
 const result=read("feed",feed,[{url:feed,body:xml}]);
 const key="feed:"+createHash('sha256').update(feed+'\nid:1').digest('hex');
 assert.deepEqual(result,{source:feed,items:[{key,text:"Field guide 更新",url:"https://example.org/articles/first"}]});
 assert.ok(read("feed",feed,[{url:feed,body:"<!DOCTYPE rss>"+xml}]).error);
 assert.ok(read("feed",feed,[{url:feed,body:"<rss><channel><item>"}]).error);
 assert.ok(read("feed",feed,[{url:feed,finalUrl:"https://other.example.org/feed",body:xml}]).error);
});

test("publisher home selects exactly one same-origin advertised feed and resolves Atom xml:base",()=>{
 const home="https://example.org/", resp=[];
 step("feed",home,resp,'<!doctype html><html><head><link rel="alternate" type="application/atom+xml" href="feed"></head><body/>');
 const atom='<feed xmlns="http://www.w3.org/2005/Atom" xml:base="/updates/"><entry><id>note:2</id><title>New publication</title><link rel="self" href="self"/><link href="paper"/><updated>2026-05-16T00:00:00Z</updated></entry></feed>';
 step("feed",home,resp,atom,u=>assert.equal(u.href,feed));
 const rows=read("feed",home,resp);
 assert.equal(rows.source,feed);
 assert.equal(rows.items[0].url,"https://example.org/updates/paper");
 assert.ok(read("feed",home,[{url:home,body:'<html><head><link rel="alternate" type="application/rss+xml" href="https://other.example.org/feed"></head></html>'}]).error);
});
