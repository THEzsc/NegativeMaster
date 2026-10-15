"""Contact-sheet layout, image handling and alpha regression checks."""
import unittest

from PIL import Image, ImageDraw

import contact_sheet as sheet


class ContactSheetTests(unittest.TestCase):
    def setUp(self):
        self.landscape=Image.new("RGB",(360,240),(217,83,41))
        self.portrait=Image.new("RGB",(240,360),(48,108,191))
        self.config={"width":1200,"columns":6,"strip":{"leader":False,"padding":0},
                     "header":{"enabled":False},"background":{"mode":"transparent"}}

    def test_size_matches_render_and_configuration_is_immutable(self):
        before=repr(self.config)
        images=[self.landscape]*7
        out=sheet.render_sheet(images,self.config,{"edge_text":"FOMAPAN 100"})
        self.assertEqual(out.size,sheet.sheet_size(7,self.config))
        self.assertEqual(out.mode,"RGBA")
        self.assertEqual(repr(self.config),before)
        self.assertEqual(sheet.sheet_layout(7,self.config).rows,2)

    def test_logical_geometry_scales_between_preview_and_export(self):
        a=sheet.sheet_layout(36,{"width":1200})
        b=sheet.sheet_layout(36,{"width":4800})
        self.assertEqual(b.margin,a.margin*4)
        self.assertEqual(b.spacing,a.spacing*4)
        self.assertEqual(b.header_height,a.header_height*4)
        self.assertAlmostEqual(b.aperture_width,a.aperture_width*4,delta=2)
        self.assertAlmostEqual(b.height,a.height*4,delta=14)

    def test_holes_reveal_background_and_preserve_alpha(self):
        layout=sheet.sheet_layout(1,self.config)
        out=sheet.render_sheet([self.landscape],self.config)
        x=layout.margin+round(layout.cell_width/16)
        y=layout.top+round(layout.band*.45+layout.cell_width*2.79/38/2)
        self.assertEqual(out.getpixel((x,y))[3],0)
        self.assertEqual(out.getpixel((0,0))[3],0)
        cx=layout.margin+round(layout.cell_width/2)
        cy=layout.top+layout.band+layout.aperture_height//2
        self.assertEqual(out.getpixel((cx,cy)),(217,83,41,255))
        solid=dict(self.config,background={"mode":"solid","color":"#abcdef"})
        self.assertEqual(sheet.render_sheet([self.landscape],solid).getpixel((x,y)),(171,205,239,255))

    def test_partial_final_row_does_not_invent_empty_frames(self):
        layout=sheet.sheet_layout(7,self.config)
        out=sheet.render_sheet([self.landscape]*7,self.config)
        y=layout.row_y(1)+layout.band+10
        x=layout.margin+round(layout.cell_width*1.5)
        self.assertEqual(out.getpixel((x,y))[3],0)

    def test_contain_cover_rotation_and_crop_are_visible(self):
        l=sheet.sheet_layout(1,self.config)
        sample=(l.margin+round(l.gap/2)+10,l.top+l.band+l.aperture_height//2)
        contain=sheet.render_sheet([self.portrait],dict(self.config,frameOverrides=[{"rotation":0}]))
        cover_c=dict(self.config,strip={"leader":False,"fit":"cover","padding":0})
        cover=sheet.render_sheet([self.portrait],cover_c)
        self.assertEqual(contain.getpixel(sample)[:3],(8,8,8))
        self.assertEqual(cover.getpixel(sample)[:3],(48,108,191))
        rotated=dict(self.config,frameOverrides=[{"rotation":90}])
        self.assertEqual(sheet.render_sheet([self.portrait],rotated).getpixel(sample)[:3],(48,108,191))
        target=Image.new("RGB",(400,200),(255,0,0))
        ImageDraw.Draw(target).rectangle((200,0,399,199),fill=(0,0,255))
        crop_c=dict(cover_c,frameOverrides=[{"crop":{"x":1,"y":.5,"scale":3}}])
        middle=(l.margin+round(l.cell_width/2),l.top+l.band+l.aperture_height//2)
        self.assertEqual(sheet.render_sheet([target],crop_c).getpixel(middle)[:3],(0,0,255))

    def test_portrait_defaults_horizontal_but_explicit_rotation_wins(self):
        portrait=Image.new("RGB",(240,360),"red")
        ImageDraw.Draw(portrait).rectangle((0,180,239,359),fill="blue")
        auto=sheet._cover(portrait,(360,240),fit="contain")
        self.assertEqual(auto.getpixel((10,120)),(0,0,255,255))
        self.assertEqual(auto.getpixel((350,120)),(255,0,0,255))
        upright=sheet._cover(portrait,(360,240),{"rotation":0},"contain")
        self.assertEqual(upright.getpixel((10,120))[3],0)
        reverse=sheet._cover(portrait,(360,240),{"rotation":270},"contain")
        self.assertEqual(reverse.getpixel((10,120)),(255,0,0,255))
        # Respect EXIF before deciding whether the source is portrait.
        landscape=Image.new("RGB",(360,240),"green")
        landscape.getexif()[274]=6
        self.assertEqual(sheet._cover(landscape,(360,240),fit="contain").getpixel((10,120))[3],255)

    def test_custom_background_is_used_without_serializing_or_mutating_it(self):
        custom=Image.new("RGB",(20,20),(8,160,82))
        cfg=dict(self.config,background={"mode":"blur","brightness":1,"sourceIndex":"custom"},
                 _backgroundImage=custom)
        out=sheet.render_sheet([self.landscape],cfg)
        self.assertEqual(out.getpixel((0,0))[:3],(8,160,82))
        self.assertIs(cfg["_backgroundImage"],custom)

    def test_gradient_runs_in_the_selected_direction(self):
        cfg=dict(self.config,background={"mode":"gradient","angle":0,"color":"#000000","color2":"#ffffff"})
        out=sheet.render_sheet([self.landscape],cfg)
        self.assertLess(out.getpixel((0,0))[0],2)
        self.assertGreater(out.getpixel((out.width-1,0))[0],253)

    def test_dot_lettering_is_present_at_preview_resolution(self):
        blank=Image.new("RGBA",(300,40),(0,0,0,255))
        sheet._text(ImageDraw.Draw(blank),(2,2),"KODAK GOLD 200",6,(230,180,80,255),"dot",290)
        self.assertGreater(len(blank.getcolors()),1)

    def test_auto_leader_fills_bottom_and_preserves_photo_indices(self):
        cfg=dict(self.config,strip={"leader":True,"padding":0})
        for count in (1,5,6,7,35,36):
            layout=sheet.sheet_layout(count,cfg)
            self.assertEqual((layout.leader_count+count)%layout.columns,0)
            self.assertGreater(layout.leader_count,0)
        l=sheet.sheet_layout(7,cfg)
        self.assertEqual((l.rows,l.leader_count),(2,5))
        photos=[self.landscape]*6+[self.portrait]
        out=sheet.render_sheet(photos,cfg)
        self.assertEqual(out.getpixel((l.margin+1,l.top+1))[3],0)
        # First and last real photographs remain in the correct slots.
        first=(l.margin+round(l.cell_width*5.5),l.top+l.band+l.aperture_height//2)
        last=(l.margin+round(l.cell_width*5.5),l.row_y(1)+l.band+l.aperture_height//2)
        self.assertEqual(out.getpixel(first)[:3],(217,83,41))
        self.assertEqual(out.getpixel(last)[:3],(48,108,191))

    def test_manual_leader_spans_rows_and_keeps_per_frame_overrides(self):
        cfg=dict(self.config,strip={"leader":True,"leaderMode":"manual","leaderCount":8,"padding":0},
                 frameOverrides=[{"rotation":90}])
        l=sheet.sheet_layout(1,cfg)
        self.assertEqual((l.rows,l.leader_count),(2,8))
        out=sheet.render_sheet([self.portrait],cfg)
        sample=(l.margin+round(l.cell_width*2)+l.gap//2+10,l.row_y(1)+l.band+l.aperture_height//2)
        self.assertEqual(out.getpixel(sample)[:3],(48,108,191))
        cfg["strip"]["leaderCount"]=0
        self.assertFalse(sheet.sheet_layout(1,cfg).leader)
        self.assertEqual(sheet.sheet_layout(1,cfg).rows,1)

    def test_leak_styles_are_deterministic_and_do_not_touch_photos_or_holes(self):
        outputs=[]
        cfg=dict(self.config,strip={"leader":True,"leaderMode":"manual","leaderCount":1,
                                  "leaderShape":"straight","padding":0})
        l=sheet.sheet_layout(1,cfg)
        for style in ("dark","clear","leak","burn","radial"):
            cfg["strip"]["leaderStyle"]=style
            out=sheet.render_sheet([self.landscape],cfg)
            self.assertEqual(out.tobytes(),sheet.render_sheet([self.landscape],cfg).tobytes())
            sample=(l.margin+round(l.cell_width*1.5),l.top+l.band+l.aperture_height//2)
            self.assertEqual(out.getpixel(sample)[:3],(217,83,41))
            hole=(l.margin+round(l.cell_width/16),l.top+round(l.band*.45+l.cell_width*2.79/38/2))
            self.assertEqual(out.getpixel(hole)[3],0)
            outputs.append(out.tobytes())
        self.assertEqual(len(set(outputs)),5)

    def test_continuous_leader_has_no_frame_gaps_and_fades_towards_photos(self):
        import numpy as np
        for style in ("leak","burn","radial"):
            cfg=dict(self.config,strip={"leader":True,"leaderMode":"manual","leaderCount":3,
                                      "leaderShape":"straight","leaderStyle":style,"leaderStrength":1})
            l=sheet.sheet_layout(1,cfg)
            out=sheet.render_sheet([self.landscape],cfg)
            boundary=l.margin+round(l.cell_width)
            y=l.top+l.band+l.aperture_height//2
            pixels=np.asarray(out).astype(int)
            self.assertLess(abs(pixels[y,boundary-1,:3]-pixels[y,boundary+1,:3]).max(),8)
            self.assertGreater(pixels[y,boundary,0],15)
            field=sheet._leader_field((1200,100),0,1,6,sheet.normalize_config(cfg)["strip"])
            array=np.asarray(field).astype(int)
            self.assertGreater(array[:,:100].mean(),array[:,-100:].mean()+30)
            self.assertLess(abs(array[:,-1,:]-8).max(),4)

    def test_background_opacity_only_changes_background_and_export_retains_alpha(self):
        for mode in ("solid","gradient","blur"):
            cfg=dict(self.config,background={"mode":mode,"opacity":.5})
            l=sheet.sheet_layout(1,cfg);out=sheet.render_sheet([self.landscape],cfg)
            self.assertEqual(out.getpixel((0,0))[3],128)
            self.assertEqual(out.getpixel((l.margin+round(l.cell_width/2),l.top+l.band+l.aperture_height//2))[3],255)

    def test_strip_separation_stays_outside_photos_and_sprockets(self):
        outputs=[]
        for effect in ("none","shadow","outline","lift","paper"):
            cfg=dict(self.config,strip={"leader":False,"padding":0,"separation":effect})
            l=sheet.sheet_layout(1,cfg);out=sheet.render_sheet([self.landscape],cfg)
            hole=(l.margin+round(l.cell_width/16),l.top+round(l.band*.45+l.cell_width*2.79/38/2))
            self.assertEqual(out.getpixel(hole)[3],0)
            self.assertEqual(out.getpixel((l.margin+round(l.cell_width/2),l.top+l.band+l.aperture_height//2)),(217,83,41,255))
            outputs.append(out.tobytes())
        self.assertEqual(len(set(outputs)),5)
        # Decorations clip safely against a zero-margin canvas.
        sheet.render_sheet([self.landscape],dict(cfg,margin=0))

    def test_new_lettering_styles_have_distinct_real_samples(self):
        samples=[]
        for style in ("dot","mono","condensed","citaro","citaro-tall","film-dot","film-stamp"):
            out=sheet.lettering_sample(style,"KODAK GOLD 200 / C-41")
            self.assertEqual(out.size,(800,156))
            self.assertGreater(len(out.getcolors(1000000)),1)
            samples.append(out.tobytes())
        self.assertEqual(len(set(samples)),7)

    def test_leader_and_header_controls_reject_invalid_values(self):
        for config in ({"strip":{"leaderCount":25}}, {"strip":{"leaderMode":"invalid"}},
                       {"strip":{"leaderStyle":"invalid"}}, {"strip":{"leaderStrength":2}},
                       {"header":{"infoScale":float("nan")}}, {"background":{"opacity":2}},
                       {"strip":{"separation":"invalid"}}, {"strip":{"separationStrength":-1}}):
            with self.assertRaises(ValueError): sheet.normalize_config(config)

    def test_invalid_inputs_and_oversized_canvas_fail_before_render(self):
        with self.assertRaisesRegex(ValueError,"至少一张"):
            sheet.render_sheet([],self.config)
        with self.assertRaisesRegex(ValueError,"80 百万"):
            sheet.sheet_size(100,{"width":10000,"columns":2})
        with self.assertRaisesRegex(ValueError,"输出宽度"):
            sheet.sheet_size(1,{"width":float("nan")})
        with self.assertRaisesRegex(ValueError,"颜色格式"):
            sheet.sheet_size(1,{"strip":{"color":"bad paint"}})


if __name__=="__main__":
    unittest.main()
