import SwiftUI

struct WorkbenchInspector: View {
  @Environment(WorkbenchState.self) var s
  private var bindings: Bindable<WorkbenchState> { Bindable(s) }
  var mode: WorkbenchState.Workspace = .develop
  @State private var hslBand = "red"
  @State private var curveChannel = "curve"
  var body: some View {
    VStack(spacing: 0) {
      HStack {
        Text(mode == .develop ? "调整" : "排版设置").font(.headline)
        Spacer()
        if mode == .develop {
          Button("重置", action: s.resetDevelop).buttonStyle(.borderless).disabled(s.selected == nil)
        }
      }.padding(16)
      if mode == .develop {
        Picker("调整面板", selection: bindings.tunePane) {
          ForEach(["光线", "色彩", "曲线", "细节", "裁剪", "导出"], id: \.self) { Text($0) }
        }.labelsHidden().padding(.horizontal, 16).padding(.bottom, 8)
        Form { developForm }.formStyle(.grouped).disabled(s.selected == nil || s.busy)
      } else {
        Picker("排版面板", selection: bindings.sheetPane) {
          Text("胶卷与边字").tag("film")
          Text("布局与片头").tag("layout")
          Text("单张构图").tag("frame")
          Text("背景与层次").tag("background")
          Text("顶部信息").tag("header")
          Text("导出与项目").tag("export")
        }.labelsHidden().padding(.horizontal, 16).padding(.bottom, 8)
        Form { sheetForm }.formStyle(.grouped).disabled(s.busy)
      }
    }.controlSize(.small)
  }
  @ViewBuilder private var developForm: some View {
    if s.tunePane == "光线" {
      Section("胶片") {
        stringPicker(
          "类型", key: "mode", choices: [("color", "彩色负片"), ("bw", "黑白负片"), ("positive", "正片")])
        Picker("预设", selection: Binding(get: { s.selectedPreset }, set: { s.applyPreset($0) })) {
          Text("自定义").tag("")
          ForEach(s.presetNames, id: \.self) { Text($0).tag($0) }
        }
        HStack {
          Button("存为预设…") { s.askName("preset") }
          Spacer()
          Button("删除预设", role: .destructive, action: s.deletePreset).disabled(
            s.selectedPreset.isEmpty)
        }
      }
      Section("直方图") {
        HistogramView(data: ["r", "g", "b"].map { s.histogram[$0].array.map { Float($0.double) } })
          .frame(height: 75)
      }
      Section("光线") {
        number("exposure", "曝光", -3...3, 0.05)
        number("gamma", "亮度 Gamma", 0.6...3, 0.05)
        number("contrast", "对比度", -0.5...0.6, 0.02)
        number("highlights", "高光", -100...100, 1)
        number("shadows", "阴影", -100...100, 1)
        number("whites", "白色", -100...100, 1)
        number("blacks", "黑色", -100...100, 1)
      }
      Section("色阶") {
        number("black_pct", "黑点百分位", 0...3, 0.1)
        number("white_pct", "白点百分位", 97...100, 0.1)
      }
      NativeWorkflowControls()
      Section("载入行为") { Toggle("载入即重置为默认参数", isOn: bindings.resetOnLoad) }
      Section("整卷") {
        Button("应用当前调整到\(s.checked.isEmpty ? "整卷":"已选照片")", action: { s.applyToRoll() })
        Button("仅把白平衡应用到整卷") { s.applyToRoll(whiteBalanceOnly: true) }
        Button("保存照片旁的 XML", action: { s.persistNow(sidecar: true) })
      }
    } else if s.tunePane == "色彩" {
      Section("白平衡") {
        stringPicker("自动白平衡", key: "wb", choices: [("gray", "灰世界"), ("none", "关闭")])
        number("temp", "色温", -100...100, 1)
        number("tint", "色调", -100...100, 1)
        sampleButton("wb_rect", "框选中性灰")
      }
      Section("色彩") {
        number("saturation", "饱和度", 0...2, 0.02)
        number("vibrance", "鲜艳度", -100...100, 1)
      }
      Section("HSL · 八色混合") {
        Picker("颜色", selection: $hslBand) {
          ForEach(
            Array(
              zip(
                ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"],
                ["红", "橙", "黄", "绿", "青", "蓝", "紫", "洋红"])), id: \.0
          ) { Text($0.1).tag($0.0) }
        }
        number("hsl.\(hslBand).h", "色相", -100...100, 1)
        number("hsl.\(hslBand).s", "饱和度", -100...100, 1)
        number("hsl.\(hslBand).l", "明亮度", -100...100, 1)
        Button("重置全部 HSL") { s.setParam("hsl", .object([:])) }
      }
      Section("参照匹配") {
        Button("选择参照成片…", action: s.pickReference)
        if !s.referenceName.isEmpty {
          Text(s.referenceName).font(.caption).foregroundStyle(.secondary)
          Toggle("启用参照匹配", isOn: boolBinding("use_match"))
          Button("清除参照", action: s.clearReference)
        }
        Text("参考照片的色调与色彩分布。启用时会替代部分基础影调设置。").font(.caption).foregroundStyle(.secondary)
      }
    } else if s.tunePane == "曲线" {
      Section("色调曲线") {
        Picker("通道", selection: $curveChannel) {
          Text("RGB").tag("curve")
          Text("红").tag("curve_r")
          Text("绿").tag("curve_g")
          Text("蓝").tag("curve_b")
        }.pickerStyle(.segmented)
        CurveEditor(
          value: Binding(get: { s.params[curveChannel] }, set: { s.setParam(curveChannel, $0) }),
          channel: curveChannel
        ).frame(height: 240)
        Text("点击添加控制点，拖动调整；双击控制点删除。").font(.caption).foregroundStyle(.secondary)
        Button("重置当前曲线") { s.setParam(curveChannel, .null) }
      }
    } else if s.tunePane == "细节" {
      Section("细节") {
        number("denoise", "色度降噪", 0...12, 1)
        number("sharpen", "锐化强度", 0...3, 0.05)
        number("sharpen_radius", "锐化半径", 0.5...5, 0.1)
        Toggle("RAW 解码降噪", isOn: boolBinding("raw_denoise"))
        number("vignette", "晕影", -100...100, 1)
      }
      Section("片基与影调取样") {
        sampleButton("film_base_rect", "框选片基")
        sampleButton("shadow_rect", "框选暗部")
        sampleButton("highlight_rect", "框选亮部")
      }
      Section("Negadoctor 冲印") {
        Toggle("启用 Negadoctor", isOn: boolBinding("negadoctor"))
        if s.params["negadoctor"].bool {
          number("nd_gamma", "纸张反差", 1...8, 0.05)
          number("nd_exposure", "印相曝光", 0.1...4, 0.05)
          number("nd_dmax", "最大密度", 0.1...6, 0.01)
          number("nd_offset", "密度偏移", -1...1, 0.01)
          number("nd_black", "黑位", -0.5...0.5, 0.005)
          number("nd_softclip", "高光柔和度", 0...1, 0.01)
        }
      }
      Section("输入") {
        stringPicker("普通图片编码", key: "input_gamma", choices: [("srgb", "sRGB"), ("linear", "线性")])
        Toggle("关闭相机白平衡", isOn: boolBinding("no_camera_wb"))
        Toggle("关闭 EXIF 自动旋转", isOn: boolBinding("no_autorotate"))
      }
    } else if s.tunePane == "裁剪" {
      Section("方向与画幅") {
        HStack {
          Button("左转") { s.rotate(-90) }
          Button("右转") { s.rotate(90) }
          Button("水平翻转") { s.mirror("h") }
          Button("垂直翻转") { s.mirror("v") }
        }
        Picker("裁剪比例", selection: bindings.cropAspect) {
          Text("自由").tag("free")
          ForEach(["3:2", "2:3", "4:3", "3:4", "1:1", "6:7", "7:6"], id: \.self) {
            Text($0).tag($0)
          }
        }.onChange(of: s.cropAspect) { _, _ in s.updateCropAspect() }
        Button(s.selectionTool == "crop" ? "完成裁剪" : "编辑裁剪框") {
          s.selectionTool = s.selectionTool == "crop" ? "" : "crop"
        }
        Button("清除裁剪") { s.setParam("crop_rect", .null) }
        Button("重置裁剪边距") { s.setParam("crop_rect", .doubles([0.06, 0.06, 0.94, 0.94])) }
        number("level_angle", "微量旋转 · 度", -15...15, 0.05)
        HStack {
          Button("−0.1°") { s.setParam("level_angle", .number(max(-15, s.params["level_angle"].double - 0.1))) }
          Button("归零") { s.setParam("level_angle", .number(0)) }
          Button("+0.1°") { s.setParam("level_angle", .number(min(15, s.params["level_angle"].double + 0.1))) }
        }
        Button("自动裁剪与校平", action: s.autoCrop)
        Toggle("参考同卷已调照片", isOn: bindings.useRollReference)
      }
    } else {
      Section("导出照片") {
        Picker("格式", selection: bindings.exportFormat) {
          Text("TIFF").tag("tif")
          Text("JPEG").tag("jpg")
          Text("PNG").tag("png")
        }
        if s.exportFormat == "tif" {
          Picker("位深", selection: bindings.exportBits) {
            Text("16 位").tag(16)
            Text("8 位").tag(8)
          }
        }
        if s.exportFormat == "jpg" {
          NumericControl(title: "JPEG 质量", value: bindings.exportQuality, range: 1...100, step: 1)
        }
        NumericControl(title: "长边像素 · 0 为原尺寸", value: bindings.exportResize, range: 0...12000, step: 100)
        Button("导出当前照片…", action: s.exportCurrent).buttonStyle(.borderedProminent)
        Button("整卷导出 \(s.filteredPhotos.count) 张…") { s.presentRollExport() }
          .disabled(s.filteredPhotos.isEmpty)
        Button("导出勾选的 \(s.visibleCheckedPhotos.count) 张…", action: s.exportBatch)
          .disabled(s.visibleCheckedPhotos.isEmpty)
        Button("发送到整卷排版…") { s.presentTransfer("sheet") }
        Button("导出到胶卷库…") { s.presentTransfer("archive") }
      }
    }
  }
  @ViewBuilder private var sheetForm: some View {
    if s.sheetPane == "film" {
      Section("胶卷资料库 · \(s.stocks.count) 款") {
        TextField("搜索品牌、型号或 ISO", text: bindings.stockSearch)
        Picker("型号", selection: Binding(get: { s.stockID }, set: { s.applyStock($0) })) {
          ForEach(
            s.stocks.filter {
              s.stockSearch.isEmpty
                || ($0["brand"].string + " " + $0["name"].string + " "
                  + String(Int($0["iso"].double))).localizedCaseInsensitiveContains(s.stockSearch)
                || $0["id"].string == s.stockID
            }, id: \.id
          ) { stock in Text(stock["name"].string).tag(stock["id"].string) }
        }
        Text(s.currentStock["brand"].string + " · " + s.currentStock["process"].string).font(
          .caption
        ).foregroundStyle(.secondary)
      }
    }
    if s.sheetPane == "frame" {
      frameForm
    } else {
      Section(
        s.sheetPane == "film"
          ? "边字与帧号"
          : s.sheetPane == "layout"
            ? "画格与片头"
            : s.sheetPane == "background" ? "背景与层次" : s.sheetPane == "header" ? "顶部信息" : "输出设置"
      ) {
        ForEach(s.fields.filter { $0.pane == s.sheetPane && visible($0.id) }) { field in
          if field.id == "background.sourceIndex" {
            Picker(
              "背景照片",
              selection: Binding(
                get: {
                  s.sheetConfig.at(field.id) == .string("custom")
                    ? "custom" : String(Int(s.sheetConfig.at(field.id).double))
                },
                set: {
                  s.setConfig(
                    field.id, $0 == "custom" ? .string("custom") : .number(Double($0) ?? 0))
                })
            ) {
              ForEach(s.sheetPhotos) { p in Text(p.name).tag(String(p.sheetID)) }
              if s.backgroundPath != nil { Text("自定义照片").tag("custom") }
            }
            Button("选择自定义背景照片…", action: s.importBackground).disabled(s.sheetJob.isEmpty)
          } else {
            SchemaControl(
              field: field,
              value: Binding(
                get: { s.sheetConfig.at(field.id) }, set: { s.setConfig(field.id, $0) }))
          }
        }
        if s.sheetPane == "layout" {
          Button("换一组漏光纹理") {
            s.setConfig("strip.leakSeed", .number(Double(Int.random(in: 1...99999))))
          }
        }
      }
    }
    if s.sheetPane == "film" {
      Section("资料依据") {
        Text(
          s.currentStock["edge_evidence"].string == "verified"
            ? "边字内容有资料依据；字形与颜色为可编辑复刻。" : "边字、字形与颜色为可编辑的近似复刻，可能随产地与年代变化。"
        ).font(.caption).foregroundStyle(.secondary)
        if !s.currentStock["notes"].string.isEmpty {
          Text(s.currentStock["notes"].string).font(.caption)
        }
        ForEach(s.currentStock["sources"].array, id: \.id) { source in
          if let u = URL(string: source["url"].string), ["http", "https"].contains(u.scheme ?? "") {
            Link(source["title"].string, destination: u).font(.caption)
          }
        }
      }
    }
    if s.sheetPane == "background" {
      Section("推荐配色") {
        HStack {
          ForEach(
            ["#d7d2c6|#65776d", "#eee3d0|#8d6346", "#e4dbe8|#4f5d77", "#f0eee8|#292e34"], id: \.self
          ) { pair in
            let colors = pair.split(separator: "|").map(String.init)
            Button {
              s.setConfig("background.mode", .string("gradient"))
              s.setConfig("background.color", .string(colors[0]))
              s.setConfig("background.color2", .string(colors[1]))
            } label: {
              RoundedRectangle(cornerRadius: 6).fill(
                LinearGradient(
                  colors: colors.map(Color.init(hex:)), startPoint: .topLeading,
                  endPoint: .bottomTrailing)
              ).frame(height: 28)
            }.buttonStyle(.plain)
          }
        }
      }
    }
    if s.sheetPane == "export" {
      Section("导出图片") {
        Picker("格式", selection: bindings.sheetFormat) {
          Text("PNG · 保留透明").tag("png")
          Text("JPEG · 分享").tag("jpg")
        }
        Text(s.outputDimensions).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        Button("导出整卷图片…", action: s.exportSheet).buttonStyle(.borderedProminent).disabled(
          s.sheetSelection.isEmpty)
      }
      Section("可编辑项目") {
        Button("保存项目…", action: s.saveProject).disabled(s.sheetSelection.isEmpty)
        Button("打开项目…", action: s.chooseProject)
        if s.draftAvailable { Button("恢复上次草稿", action: s.restoreDraft) }
        Text("项目包保存照片、背景和排版，可在网页版与 Mac 版之间继续编辑。").font(.caption).foregroundStyle(.secondary)
      }
      Section("版式预设") {
        Picker("已存版式", selection: Binding(get: { s.selectedLayout }, set: { s.applyLayout($0) })) {
          Text("选择版式").tag("")
          ForEach(s.layoutNames, id: \.self) { Text($0).tag($0) }
        }
        Button("保存当前版式…") { s.askName("layout") }
        Button("删除版式", role: .destructive, action: s.deleteLayout).disabled(
          s.selectedLayout.isEmpty)
      }
    }
  }
  @ViewBuilder private var frameForm: some View {
    if let p = s.activePhoto {
      Section(p.name) {
        HStack {
          Button("上一张") {
            if let i = s.sheetPhotos.firstIndex(of: p), i > 0 {
              s.activateFrame(s.sheetPhotos[i - 1].sheetID)
            }
          }
          Button("下一张") {
            if let i = s.sheetPhotos.firstIndex(of: p), i + 1 < s.sheetPhotos.count {
              s.activateFrame(s.sheetPhotos[i + 1].sheetID)
            }
          }
        }
        Button("查看单张构图") { s.activateFrame(p.sheetID) }
        HStack {
          Button("左转") { s.rotateFrame(-90) }
          Button("右转") { s.rotateFrame(90) }
          Button("前移") { s.moveFrame(-1) }
          Button("后移") { s.moveFrame(1) }
        }
        TextField(
          "单帧标签",
          text: Binding(
            get: { s.frameValue("label").string }, set: { s.setFrame("label", .string($0)) }))
        Picker(
          "填充",
          selection: Binding(
            get: { s.frameValue("fit", fallback: s.sheetConfig.at("strip.fit")).string },
            set: { s.setFrame("fit", .string($0)) })
        ) {
          Text("完整显示").tag("contain")
          Text("铺满窗口").tag("cover")
        }
        NumericControl(title: "放大", value: frameBinding("crop.scale", 1), range: 1...8, step: 0.05)
        NumericControl(title: "水平中心", value: frameBinding("crop.x", 0.5), range: 0...1, step: 0.01)
        NumericControl(title: "垂直中心", value: frameBinding("crop.y", 0.5), range: 0...1, step: 0.01)
        Toggle("三分构图线", isOn: bindings.frameGrid)
        Button("重置构图", action: s.resetFrame)
        Button(s.sheetSelection.contains(p.sheetID) ? "移出排版" : "加入排版") { s.toggleFrame(p.sheetID) }
      }
    } else {
      Text("从左侧选择照片，调整旋转、裁切位置与排列顺序。").foregroundStyle(.secondary)
    }
  }
  private func frameBinding(_ key: String, _ fallback: Double) -> Binding<Double> {
    Binding(
      get: { s.frameValue(key, fallback: .number(fallback)).double },
      set: { s.setFrame(key, .number($0)) })
  }
  private func visible(_ key: String) -> Bool {
    let c = s.sheetConfig
    if key == "strip.leaderCount" {
      return c.at("strip.leader").bool && c.at("strip.leaderMode").string == "manual"
    }
    if ["strip.leaderMode", "strip.leaderShape"].contains(key) { return c.at("strip.leader").bool }
    if ["strip.sprocketStyle", "strip.sprocketRim"].contains(key) {
      return c.at("strip.sprockets").bool
    }
    if key.hasPrefix("background.") {
      let mode = c.at("background.mode").string
      if ["background.sourceIndex", "background.blur", "background.brightness"].contains(key) {
        return mode == "blur"
      }
      if key == "background.color" { return ["solid", "gradient"].contains(mode) }
      if ["background.color2", "background.angle"].contains(key) { return mode == "gradient" }
    }
    return true
  }
  private func number(_ key: String, _ title: String, _ range: ClosedRange<Double>, _ step: Double)
    -> some View
  {
    NumericControl(
      title: title,
      value: Binding(get: { s.params.at(key).double }, set: { s.setParam(key, .number($0)) }),
      range: range, step: step)
  }
  private func boolBinding(_ key: String) -> Binding<Bool> {
    Binding(get: { s.params.at(key).bool }, set: { s.setParam(key, .bool($0)) })
  }
  private func stringPicker(_ title: String, key: String, choices: [(String, String)]) -> some View
  {
    Picker(
      title,
      selection: Binding(get: { s.params[key].string }, set: { s.setParam(key, .string($0)) })
    ) { ForEach(choices, id: \.0) { Text($0.1).tag($0.0) } }
  }
  private func sampleButton(_ key: String, _ title: String) -> some View {
    HStack {
      Button(s.selectionTool == key ? "取消取样" : title) {
        s.selectionTool = s.selectionTool == key ? "" : key
      }
      Spacer()
      if s.params[key] != .null { Button("清除") { s.setParam(key, .null) } }
    }
  }
}

struct NumericControl: View {
  let title: String
  @Binding var value: Double
  let range: ClosedRange<Double>
  var step = 1.0
  var body: some View {
    VStack(spacing: 6) {
      HStack {
        Text(title)
        Spacer()
        TextField(
          title,
          value: Binding(
            get: { value },
            set: {
              value = min(
                range.upperBound, max(range.lowerBound, $0.isFinite ? $0 : range.lowerBound))
            }), format: .number.precision(.fractionLength(step >= 1 ? 0 : 2))
        ).labelsHidden().multilineTextAlignment(.trailing).textFieldStyle(.plain).font(
          .system(.caption, design: .monospaced)
        ).frame(width: 64).accessibilityLabel(title + "数值")
      }
      Slider(value: $value, in: range, step: step).labelsHidden().accessibilityLabel(title)
    }.padding(.vertical, 3)
  }
}
struct SchemaControl: View {
  let field: ControlField
  @Binding var value: J
  var body: some View {
    switch field.kind {
    case "checkbox":
      Toggle(field.title, isOn: Binding(get: { value.bool }, set: { value = .bool($0) }))
    case "range", "number":
      NumericControl(
        title: field.title, value: Binding(get: { value.double }, set: { value = .number($0) }),
        range: field.value["min"]
          .double...max(field.value["min"].double, field.value["max"].double),
        step: field.value["step"].double)
    case "color":
      RecommendedColor(field: field, value: $value)
    case "select":
      Picker(
        field.title,
        selection: Binding(
          get: {
            field.value["boolean"].bool
              ? (value.bool ? "true" : "false")
              : (field.id == "width" ? String(Int(value.double)) : value.string)
          },
          set: {
            value =
              field.value["boolean"].bool
              ? .bool($0 == "true")
              : field.id == "width" ? .number(Double($0) ?? 4800) : .string($0)
          })
      ) {
        ForEach(field.value["options"].array, id: \.id) { o in
          Text(o["label"].string).tag(o["value"].string)
        }
      }
    default:
      TextField(
        field.title,
        text: Binding(get: { value.string }, set: { value = .string(String($0.prefix(220))) }),
        axis: field.id == "header.notes" ? .vertical : .horizontal)
    }
  }
}
