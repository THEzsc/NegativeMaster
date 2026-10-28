import SwiftUI

struct RecommendedColor: View {
  let field: ControlField
  @Binding var value: J
  @State private var customHex = ""
  @State private var invalidHex = false
  var choices: [(String,String)] {
    switch field.id {
    case "strip.color": return [("胶片黑","#080808"),("暖黑","#1a1511"),("石墨","#343637"),("蓝黑","#15232a"),("墨绿","#172721"),("深褐","#39251e")]
    case "strip.edgeColor": return [("琥珀","#dda850"),("金黄","#edbd63"),("乳白","#eee6d8"),("珊瑚","#df8c6b"),("浅绿","#bdd0a5"),("雾蓝","#bacbd6")]
    case "header.color": return [("档案白","#fffdfa"),("暖纸","#e8e1d3"),("冷白","#edf1f2"),("浅绿","#dce3d8"),("浅杏","#eddbca"),("炭黑","#202122")]
    case "header.textColor": return [("墨黑","#191a1b"),("深褐","#49352b"),("墨绿","#243b32"),("夜蓝","#243d4d"),("砖红","#803d2f"),("乳白","#fffdfa")]
    default: return [("暖纸","#e8e1d3"),("冷雾","#c3ced0"),("鼠尾草","#a4b1a0"),("灰蓝","#697d8b"),("焦糖","#98704f"),("炭灰","#292b2b"),("夜蓝","#1e3039"),("豆沙","#916c69")]
    }
  }
  var body: some View {
    VStack(alignment:.leading,spacing:10) {
      Text(field.title)
      LazyVGrid(columns:[GridItem(.adaptive(minimum:62))],spacing:8) {
        ForEach(choices,id:\.1) { name,hex in
          Button { value = .string(hex) } label: {
            VStack(spacing:4) {
              RoundedRectangle(cornerRadius:4).fill(Color(hex:hex)).frame(height:22)
                .overlay(RoundedRectangle(cornerRadius:4).strokeBorder(value.string.lowercased() == hex ? Color.accentColor : Color.secondary.opacity(0.3),lineWidth:value.string.lowercased() == hex ? 2 : 0.5))
              Text(name).font(.caption).foregroundStyle(.primary)
            }
          }.buttonStyle(.plain).accessibilityLabel(field.title+"："+name).accessibilityAddTraits(value.string.lowercased() == hex ? [.isSelected] : [])
        }
      }
      DisclosureGroup("自定义颜色") {
        ColorPicker("颜色",selection:Binding(get:{Color(hex:value.string)},set:{value = .string($0.hex)}),supportsOpacity:false)
        TextField("HEX",text:$customHex).onSubmit {
          invalidHex = customHex.range(of:"^#[0-9a-fA-F]{6}$",options:.regularExpression) == nil
          if !invalidHex { value = .string(customHex) }
        }
        if invalidHex { Text("请输入 # 加六位十六进制色值。").font(.caption).foregroundStyle(.orange) }
      }
    }.padding(.vertical,4).onAppear { customHex = value.string }.onChange(of:value) { _,v in customHex = v.string; invalidHex = false }
  }
}
