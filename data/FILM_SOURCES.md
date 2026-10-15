# 胶卷型号与片边字资料

研究日期：2026-10-15。`film_stocks.json` 收录 100 个型号 / 包装命名，覆盖 12 个品牌；27 条边字字串有厂家直接资料，73 条为可编辑的近似预设。它是排版资料库，不是现行库存表、胶片鉴定器或色彩预设库。

## 如何理解证据

- `verified` 只表示 `edge_text` 字串在所引厂家的 Edge Print 字段、边字表或图中有直接依据；不表示字体、墨色、曝光效果、字距和位置已精确复刻，更不保证跨年份、片幅和批次一致。
- `approximate` 的字串按型号名称重建，或参考独立摄影者的实物记录但缺少可以逐字检查的片边图。界面应显示「近似边字」，允许用户替换成手中底片的实印。
- `font_style` 的 `dot`、`condensed`、`mono` 是点阵、窄体、等宽三种视觉方向。没有把任何商业字体或开源字体冒充厂家专有的片边字体。字形轮廓也应可编辑。
- `edge_color` 是在黑底胶条排版中的展示色，不是胶片染料色度测量。反转、扫描白平衡、反色和曝光都能改变片边的视觉颜色。
- 未核实的副码保持空白。仅 C200 的 CA24 与 SUPERIA PREMIUM 400 的 CH24 据厂家表填写，它们是特定资料版次的代际码，不是 DX 码，也不是固定乳剂批号。不要自动生成可被误认成真实 DX / KeyKode 的码。

## 已核对的型号与字串

Kodak 的 9 条字串来自 Kodak Alaris 产品页的明确 Edge Print 字段：PORTRA 160、400、800，EKTAR 100，E100，400TX，100TMX，400TMY-2，P3200TMZ。各条 JSON 都指向对应页。新 EKTACOLOR / EKTAPAN 包装名称的存在由当前 Kodak 官网确认，但没有把旧型号的印字直接搬成新包装的「已验证边字」。

Fujifilm 的 18 条字串来自厂家原始资料。2005 年 Professional Film Data Guide 印刷页 18–21 提供 FUJICHROME / FUJICOLOR 边字对照；页 79 提供原版 ACROS。此资料主要对应当年的 135 印字；例如 PRO 400H 的 135 缩写是 400，而 120 可用 PRO 400H，不能跨格式宣称字串完全相同。另有 C200 技术资料第 13 节（200 / CA24）和 SUPERIA PREMIUM 400 技术资料第 15 节（S-400 / CH24）。

## 感光度与版本

`iso` 为数值，便于排序和排版；它不是全库统一的实验测定结果。T-MAX P3200 以厂家明确的原生 ISO 800 建档，DELTA 3200 以 ISO 1000 建档，产品名称仍保留 3200。EKTAPAN P3200 当前页只明确推荐增感到 3200，因此这里用 3200 作排版默认值，并在记录中说明原生 ISO 未核对。BwXX / DOUBLE-X 用日光 EI 250；ORTHO PLUS 用日光 EI 80。LomoChrome 100–400 和 Redscale 50–200 用范围下限作默认值，完整范围在名称和备注中保留。

年代、地区、片幅、散装分装和包装更新都会影响印字。目录保留 ACROS 原版 / II、Phoenix 原版 / II、旧 Kodak 与新官网命名，方便旧卷排版；没有仅凭名称断言乳剂相同。AgfaPhoto APX 没有被自动当作历史 AGFA APX，Lucky SHD 新一代也没有被自动当作旧 SHD。

## 实物照片参考

[35milly 的 Gold 200 实物片边照片](https://35milly.com/en/how-to-identify-the-emulsion-side-of-the-film-with-photos/) 用于观察字的位置、字色和齿孔关系。[Dmitri / Analog.Cafe 的 ColorPlus 本人拍摄、扫描与印字记录](https://www.analog.cafe/r/kodak-colorplus-200-film-review-fygr) 提供 200-8 KODAK 这一实物字串参考；没有据其乳剂推测作型号映射。两者均只作外观参考，没有下载、打包或复制作者照片，也未据低分辨率图片声明精确字体匹配。

## 主要原始资料

每条记录的 `sources` 保存具体来源，下列为去重清单。厂家的产品页、技术说明、产品目录或由发行主体撰写的公司报告用于型号、感光度、处理类型和规格。乐凯商城为动态页面；其 SHD 型号由乐凯发布的 ESG / 社会责任报告交叉确认。PDF 文件名里的上传年份不代表文件内容版次。

- [Kodak GOLD 200 product page](https://www.kodak.com/en/still-film/product/consumer/gold-200-film/)
- [35milly：实物 Gold 200 片边照片（外观参考，未将其当作字体文件）](https://35milly.com/en/how-to-identify-the-emulsion-side-of-the-film-with-photos/)
- [Kodak ULTRAMAX 400 product page](https://www.kodak.com/en/still-film/product/consumer/ultramax-400-film/)
- [Kodak Professional Film Catalogue (2024), consumer film range](https://kodakprofessional.com/sites/default/files/files/resources/Kodak%20Catalogue%20-%20Final%20-%20High%20Res%20%28Print%29.pdf)
- [Kodak Alaris：C-41 color film processing resources](https://www.kodakprofessional.com/photographers/resources)
- [Dmitri / Analog.Cafe：本人拍摄与扫描的 ColorPlus，实印字串 200-8 KODAK](https://www.analog.cafe/r/kodak-colorplus-200-film-review-fygr)
- [Kodak Alaris PORTRA 160：Edge Print field](https://www.kodakprofessional.com/photographers/film/color/kodak-professional-portra-160-film/529)
- [Kodak Alaris PORTRA 400：Edge Print field](https://www.kodakprofessional.com/photographers/film/color/kodak-professional-portra-400-film/516)
- [Kodak Alaris PORTRA 800：Edge Print field](https://www.kodakprofessional.com/photographers/film/color/kodak-professional-portra-800-film/528)
- [Kodak Alaris EKTAR 100：Edge Print field](https://www.kodakprofessional.com/photographers/film/color/kodak-professional-ektar-100-film/530)
- [Kodak Alaris E100：Edge Print field](https://www.kodakprofessional.com/photographers/film/color/kodak-professional-ektachrome-film-e100/531)
- [Kodak Alaris TRI-X 400：ISO and Edge Print fields](https://www.kodakprofessional.com/photographers/film/black-white/kodak-professional-tri-x-films/515)
- [Kodak Alaris T-MAX 100：ISO and Edge Print fields](https://www.kodakprofessional.com/photographers/film/black-white/kodak-professional-t-max-100-film/525)
- [Kodak Alaris T-MAX 400：ISO and Edge Print fields](https://www.kodakprofessional.com/photographers/film/black-white/kodak-professional-t-max-400-film/526)
- [Kodak Alaris T-MAX P3200：ISO and Edge Print fields](https://www.kodakprofessional.com/photographers/film/black-white/kodak-professional-t-max-p3200-film/527)
- [Kodak VISION3 50D 5203 / 7-series product page](https://www.kodak.com/en/motion/product/camera-films/50d-5203-7203/)
- [Kodak VISION3 200T 5213 / 7-series product page](https://www.kodak.com/en/motion/product/camera-films/200t-5213-7213/)
- [Kodak VISION3 250D 5207 / 7-series product page](https://www.kodak.com/en/motion/product/camera-films/250d-5207-7207/)
- [Kodak VISION3 500T 5219 / 7-series product page](https://www.kodak.com/en/motion/product/camera-films/500t-5219-7219/)
- [Kodak EASTMAN DOUBLE-X 5222/7222](https://www.kodak.com/en/motion/product/camera-films/eastman-double-x-black-white-5222-7222/)
- [Kodak EKTACOLOR PRO 160](https://www.kodak.com/en/still-film/product/professional/ektacolor/ektacolor-pro-160-film/)
- [Kodak EKTACOLOR PRO 400](https://www.kodak.com/en/still-film/product/professional/ektacolor/ektacolor-pro-400-film/)
- [Kodak EKTACOLOR PRO 800](https://www.kodak.com/en/still-film/product/professional/ektacolor/ektacolor-pro-800-film/)
- [Kodak EKTAPAN 100 current product page](https://www.kodak.com/en/still-film/product/professional/ektapan/ektapan-100-film/)
- [Kodak EKTAPAN 400 current product page](https://www.kodak.com/en/still-film/product/professional/ektapan/ektapan-400-film/)
- [Kodak EKTAPAN P3200 current product page](https://www.kodak.com/en/still-film/product/professional/ektapan/ektapan-p3200-film/)
- [Kodak KODACOLOR 200](https://www.kodak.com/en/still-film/product/consumer/kodacolor-200-film/)
- [Fujifilm Professional Film Data Guide (2005), pp. 8–15, 18–21, 72–79](https://asset.fujifilm.com/www/us/files/2020-04/9cdee030ab7fc76bbcfddbcd38650038/ProfessionalFilmDataGuide.pdf)
- [Fujifilm Japan film product range](https://www.fujifilm.com/jp/ja/consumer/films/negative-and-reversal)
- [Fujicolor C200 Product Information Bulletin](https://asset.fujifilm.com/www/us/files/2019-09/cce1e1943550fc3e76c22411066f0100/films_c200_datasheet_01.pdf)
- [SUPERIA PREMIUM 400 Product Information Bulletin](https://asset.fujifilm.com/www/jp/files/2019-12/3723e0912cf7e939bb07fd982b0ff9fa/datasheet_superiapremium400_01.pdf)
- [ILFORD product brochure：film speeds, types and formats](https://www.ilfordphoto.com/wp/wp-content/uploads/2017/05/Ilford-Product-Brochure-LOW-RES-WEB-1.pdf)
- [ILFORD DELTA 3200 Technical Information：ISO speed rating](https://www.ilfordphoto.com/amfile/file/download/file/1913/product/682/)
- [ILFORD ORTHO PLUS film and processing chart](https://www.ilfordphoto.com/amfile/file/download/file/1953/product/699/)
- [ILFORD regional product handbook (2018), PAN 100 / PAN 400](https://www.ilfordphoto.cz/wp-content/uploads/2018/08/P%C5%98%C3%8DRU%C4%8CKA_ILFORD_2018.pdf)
- [ILFORD / HARMAN Kentmere PAN 100](https://www.ilfordphoto.com/kentmere-100-120)
- [ILFORD / HARMAN Kentmere PAN 200](https://www.ilfordphoto.com/kentmere-200-35mm)
- [ILFORD / HARMAN Kentmere PAN 400](https://www.ilfordphoto.com/kentmere-400-120)
- [FOMA official black-and-white film catalogue](https://www.foma.cz/en/catalogue-bw-film-324)
- [FOMA official product handbook, formats and processing](https://www.foma.cz/ew/92cad2bd-ec2b-4442-bc3c-b13be9ea63ff-fr)
- [FOMA ORTHO 400 official technical data sheet](https://www.foma.cz/en/fomaortho)
- [FOMAPAN R 100 official technical data sheet](https://www.foma.cz/en/fomapan-R-100)
- [乐凯官方影像商城：SHD100 / SHD400 黑白胶卷](https://www.lucky.cn/index/home)
- [乐凯胶片股份有限公司 2023 ESG / 社会责任报告：新一代 SHD100 / SHD400 产品](https://pdf.dfcfw.com/pdf/H2_AN202403281628446070_1.pdf)
- [AgfaPhoto official APX 100 / 400 product range](https://agfaphoto.com/en/analog-photography-single-use-cameras/)
- [ADOX official CHS 100 II](https://www.adox.de/films/chs100ii-en/)
- [ADOX official HR-50](https://www.adox.de/hr50-en/)
- [ADOX official CMS 20 II](https://www.adox.de/films/cms20ii-en/)
- [ADOX official SCALA 50](https://www.adox.de/scala50-en/)
- [ADOX official SCALA 160](https://www.adox.de/scala160-en/)
- [Rollei RETRO 80S official datasheet, film range comparison](https://www.rolleianalog.com/wp-content/uploads/2021/02/RETRO80S_Datenblatt_EN_R012101.pdf)
- [CineStill official four-film medium-format lineup](https://cinestillfilm.com/blogs/news/120-medium-format)
- [CineStill official film processing FAQ](https://cinestillfilm.com/pages/frequently-asked-questions)
- [CineStill official BwXX exposure and development guide](https://cinestillfilm.com/pages/bwxx-dev-times)
- [Lomography manufacturer film guides download index](https://cdn.downloads.lomography.com/downloads/)
- [Lomography：What are LomoChrome films?](https://www.lomography.com/school/what-are-lomochrome-films-fa-g3ebpber)
- [Lomography Color ’92 official product specification](https://shop.lomography.com/us/lomochrome-color-92-35-mm-iso-400?source=nl_color_92_reacts)
- [Lomography Redscale XR 50–200 official product specification](https://www.lomography.cn/products/f136xr3/)
- [HARMAN official Phoenix 200 product specification](https://www.harmanphoto.co.uk/harman-phoenix-200)
- [HARMAN official Phoenix II product specification](https://www.harmanphoto.co.uk/harman-phoenix-ii-120)
- [HARMAN official RED 125 product specification](https://www.harmanphoto.co.uk/harman-red-125-35mm)
- [HARMAN official SWITCH AZURE product specification](https://www.harmanphoto.co.uk/harman-switch-azure-35mm)
