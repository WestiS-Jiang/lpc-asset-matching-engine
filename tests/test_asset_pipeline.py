import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
import scanner
from fastapi import HTTPException
from fastapi.testclient import TestClient


class ScannerTests(unittest.TestCase):
    def test_scan_manifest_contains_core_categories(self) -> None:
        result = scanner.scan_sheet_definitions(
            scanner.DEFAULT_DEFINITIONS_ROOT,
            scanner.DEFAULT_SPRITES_ROOT,
        )
        manifest = result["manifest"]
        self.assertIn("body", manifest)
        self.assertIn("hair", manifest)
        self.assertIn("armor", manifest)
        self.assertIn("weapons", manifest)
        self.assertIn("weapon_sword_longsword", manifest["weapons"])

    def test_scan_manifest_includes_non_core_categories(self) -> None:
        result = scanner.scan_sheet_definitions(
            scanner.DEFAULT_DEFINITIONS_ROOT,
            scanner.DEFAULT_SPRITES_ROOT,
        )
        manifest = result["manifest"]
        self.assertIn("head", manifest)
        self.assertGreater(len(manifest["head"]), 0)

    def test_scan_items_include_semantic_tags(self) -> None:
        result = scanner.scan_sheet_definitions(
            scanner.DEFAULT_DEFINITIONS_ROOT,
            scanner.DEFAULT_SPRITES_ROOT,
        )
        item = result["items_by_id"]["weapon_ranged_crossbow"]
        self.assertIn("weapon.crossbow", item["semantic_tags"])
        self.assertIn("weapon.ranged", item["semantic_tags"])


class AnalyzeMappingTests(unittest.TestCase):
    def test_missing_assets_mapped_from_generation_tasks(self) -> None:
        tasks = [
            {
                "category": "weapons",
                "internal_name": "nunchuck_wooden",
                "gen_prompt": "prompt from model",
                "visual_prompt": "visual prompt from model",
                "design_notes": "align to LPC hand grip",
            }
        ]
        missing = main.build_missing_assets(tasks)
        self.assertEqual(1, len(missing))
        self.assertEqual("nunchuck_wooden", missing[0]["internal_name"])
        self.assertEqual("visual prompt from model", missing[0]["visual_prompt"])
        self.assertEqual("align to LPC hand grip", missing[0]["design_notes"])

    def test_validate_extended_layers_filters_unknown_item_ids(self) -> None:
        items_by_id = {
            "hat_duckbill_cap": {"item_id": "hat_duckbill_cap"},
            "face_neutral": {"item_id": "face_neutral"},
        }
        extended = {
            "hat": "hat_duckbill_cap",
            "expression": "face_neutral",
            "cape": "not_exists",
        }
        out = main._validate_extended_layers(extended, items_by_id)
        self.assertEqual("hat_duckbill_cap", out["hat"])
        self.assertEqual("face_neutral", out["expression"])
        self.assertNotIn("cape", out)

    def test_tokenize_expands_chinese_weapon_synonyms(self) -> None:
        tokens = main._tokenize("我要步枪，不要十字弩")
        self.assertIn("rifle", tokens)
        self.assertIn("crossbow", tokens)

    def test_local_similarity_prefers_rifle_for_chinese_prompt(self) -> None:
        candidates = [
            {
                "item_id": "weapon_ranged_crossbow",
                "search_text": "weapon ranged crossbow bow",
                "layer_count": 2,
            },
            {
                "item_id": "weapon_ranged_firearm_rifle",
                "search_text": "weapon ranged firearm rifle gun",
                "layer_count": 2,
            },
        ]
        picked = main._local_similarity_select(prompt_text="角色使用步枪", candidates=candidates)
        self.assertEqual("weapon_ranged_firearm_rifle", picked)

    def test_local_similarity_prefers_blade_over_crossbow_for_dadao(self) -> None:
        candidates = [
            {
                "item_id": "weapon_ranged_crossbow",
                "search_text": "weapon ranged crossbow bow",
                "semantic_tags": ["weapon.crossbow", "weapon.ranged"],
                "layer_count": 2,
                "primary_category": "weapons",
            },
            {
                "item_id": "weapon_sword_longsword",
                "search_text": "weapon melee sword longsword blade",
                "semantic_tags": ["weapon.sword", "weapon.melee"],
                "layer_count": 2,
                "primary_category": "weapons",
            },
        ]
        picked = main._semantic_similarity_select(
            prompt_text="年轻女性，拿大刀",
            candidates=candidates,
            category="weapons",
        )
        self.assertEqual("weapon_sword_longsword", picked)

    def test_manifest_context_for_prompt_contains_display_names(self) -> None:
        scan_result = {
            "summary": {"total_items": 1, "top_folders": []},
            "manifest": {"weapons": ["weapon_sword_longsword"]},
            "items_by_id": {
                "weapon_sword_longsword": {
                    "display_name": "Longsword",
                    "type_name": "weapon",
                    "primary_category": "weapons",
                    "path_parts": ["weapons", "sword"],
                    "semantic_tags": ["weapon.sword"],
                    "variant_tokens": [],
                    "recolor_tokens": [],
                    "search_text": "weapon sword longsword",
                }
            },
        }
        context_json = main._build_manifest_context_for_prompt(
            scan_result,
            prompt_text="warrior with longsword",
            include_custom=True,
        )
        self.assertIn("Longsword", context_json)
        self.assertIn("weapon_sword_longsword", context_json)


class TemplateSelectionTests(unittest.TestCase):
    def test_template_selection_falls_back_to_standard_template(self) -> None:
        candidates = [
            {
                "item_id": "weapon_ancient_meteor_blade",
                "display_name": "Ancient Meteor Blade",
                "is_standard_template": False,
                "layer_count": 2,
                "zpos_signature": (50, 120),
                "search_text": "weapon ancient meteor blade",
            },
            {
                "item_id": "weapon_standard_sword",
                "display_name": "Standard Sword",
                "is_standard_template": True,
                "layer_count": 2,
                "zpos_signature": (50, 120),
                "search_text": "weapon standard sword",
            },
        ]
        selected = main.select_template_candidate(
            requested_internal_name="thunderstorm_blade_of_ruin",
            candidates=candidates,
            similarity_threshold=0.3,
        )
        self.assertEqual("weapon_standard_sword", selected["item_id"])
        self.assertEqual("standard_template_fallback", selected["selection_reason"])

    def test_template_selection_falls_back_to_most_complete_layers(self) -> None:
        candidates = [
            {
                "item_id": "weapon_minimal",
                "display_name": "Weapon Minimal",
                "is_standard_template": False,
                "layer_count": 1,
                "zpos_signature": (120,),
                "search_text": "weapon minimal",
            },
            {
                "item_id": "weapon_complete",
                "display_name": "Weapon Complete",
                "is_standard_template": False,
                "layer_count": 4,
                "zpos_signature": (10, 20, 140, 150),
                "search_text": "weapon complete",
            },
        ]
        selected = main.select_template_candidate(
            requested_internal_name="thunderstorm_blade_of_ruin",
            candidates=candidates,
            similarity_threshold=0.3,
        )
        self.assertEqual("weapon_complete", selected["item_id"])
        self.assertEqual("most_complete_layers_fallback", selected["selection_reason"])


class PrecheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="sprite-precheck-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_precheck_requires_png(self) -> None:
        with self.assertRaises(ValueError):
            main.precheck_spritesheet_root(self.temp_dir, ["walk", "idle"])

    def test_precheck_accepts_png_with_animation_hint(self) -> None:
        walk_dir = self.temp_dir / "walk"
        walk_dir.mkdir(parents=True, exist_ok=True)
        (walk_dir / "frame_01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        result = main.precheck_spritesheet_root(self.temp_dir, ["walk", "idle"])
        self.assertEqual(1, result["png_count"])
        self.assertTrue(result["animation_hint_matched"])


class SingleImagePipelineTests(unittest.TestCase):
    def test_two_stage_downscale_threshold(self) -> None:
        self.assertTrue(main._should_use_two_stage_downscale(1024, 1024, 64))
        self.assertFalse(main._should_use_two_stage_downscale(160, 160, 64))

    def test_alignment_fallback_modes(self) -> None:
        self.assertEqual(
            ("bottom_center", 0, 0),
            main._resolve_canvas_alignment(category="weapons", preview_x_offset=None, preview_y_offset=None),
        )
        self.assertEqual(
            ("center", 0, 0),
            main._resolve_canvas_alignment(category="armor", preview_x_offset=None, preview_y_offset=None),
        )
        self.assertEqual(
            ("template_offset", 3, -2),
            main._resolve_canvas_alignment(category="armor", preview_x_offset=3, preview_y_offset=-2),
        )

    def test_build_targets_preserves_nested_animation_paths(self) -> None:
        template_definition = {
            "variants": ["longsword"],
            "animations": ["walk", "slash", "1h_backslash"],
            "layer_1": {
                "male": "weapon/sword/longsword/",
            },
            "layer_2": {
                "custom_animation": "thrust_oversize",
                "male": "weapon/sword/longsword/attack_thrust/",
            },
        }
        new_definition = {
            "variants": ["thunder_blade"],
            "animations": ["walk", "slash", "1h_backslash"],
            "layer_1": {
                "male": "weapon/custom/thunder_blade/",
            },
            "layer_2": {
                "custom_animation": "thrust_oversize",
                "male": "weapon/custom/thunder_blade/attack_thrust/",
            },
        }

        targets = main._build_single_image_targets(
            template_definition=template_definition,
            new_definition=new_definition,
            template_item_id="weapon_sword_longsword",
            output_variant="thunder_blade",
        )
        output_paths = [item["output_rel"].as_posix() for item in targets]

        self.assertIn("weapon/custom/thunder_blade/walk/thunder_blade.png", output_paths)
        self.assertIn("weapon/custom/thunder_blade/slash/thunder_blade.png", output_paths)
        self.assertIn("weapon/custom/thunder_blade/backslash/thunder_blade.png", output_paths)
        self.assertIn("weapon/custom/thunder_blade/attack_thrust/thunder_blade.png", output_paths)
        self.assertEqual(len(output_paths), len(set(output_paths)))


class GenModeTests(unittest.TestCase):
    def test_resolve_gen_mode_uses_runtime_default(self) -> None:
        with patch(
            "main.load_relay_config",
            return_value=SimpleNamespace(
                runtime=SimpleNamespace(
                    gen_mode_default=False,
                    max_generation_tasks=2,
                    lpc_only_exclude_custom=True,
                )
            ),
        ):
            self.assertFalse(main.resolve_gen_mode(None))
            self.assertTrue(main.resolve_gen_mode(True))

    def test_lpc_only_fallback_fills_all_primary_layers(self) -> None:
        scan_result = scanner.scan_sheet_definitions(
            scanner.DEFAULT_DEFINITIONS_ROOT,
            scanner.DEFAULT_SPRITES_ROOT,
        )
        with patch(
            "main.load_relay_config",
            return_value=SimpleNamespace(
                runtime=SimpleNamespace(
                    gen_mode_default=False,
                    max_generation_tasks=2,
                    lpc_only_exclude_custom=True,
                )
            ),
        ):
            out = main._apply_lpc_only_fallback(
                validated_layers=main.SelectedLayers(),
                prompt_text="%%%###火星乱码%%%###",
                scan_result=scan_result,
            )
        self.assertEqual("body", out.body)
        self.assertEqual("hair_single", out.hair)
        self.assertEqual("torso_armour_plate", out.armor)
        self.assertEqual("weapon_sword_longsword", out.weapons)

    def test_validate_selected_layers_accepts_dress_for_armor_slot(self) -> None:
        manifest = {
            "body": ["body"],
            "hair": ["hair_single"],
            "armor": ["torso_armour_plate"],
            "torso": ["dress_kimono"],
            "weapons": ["weapon_sword_longsword"],
        }
        out = main._validate_selected_layers(
            main.SelectedLayers(
                body="body",
                hair="hair_single",
                armor="dress_kimono",
                weapons="weapon_sword_longsword",
            ),
            manifest,
        )
        self.assertEqual("dress_kimono", out.armor)

    def test_dedupe_extended_torso_when_same_as_armor(self) -> None:
        selected = main.SelectedLayers(
            body="body",
            hair="hair_single",
            armor="dress_kimono",
            weapons="weapon_sword_longsword",
        )
        extended = {"torso": "dress_kimono", "feet": "feet_shoes_basic"}
        out = main._dedupe_overlapping_layers(selected, extended)
        self.assertNotIn("torso", out)
        self.assertEqual("feet_shoes_basic", out["feet"])

    def test_filter_incompatible_layers_by_body_type(self) -> None:
        selected = main.SelectedLayers(
            body="body",
            hair="hair_wavy_child",
            armor="dress_kimono",
            weapons="weapon_sword_longsword",
        )
        extended = {}
        scan_result = {
            "items_by_id": {
                "body": {"supports_body_types": ["female", "male", "child"]},
                "hair_wavy_child": {"supports_body_types": ["child"]},
                "dress_kimono": {"supports_body_types": ["female", "male"]},
                "weapon_sword_longsword": {"supports_body_types": []},
            }
        }
        out_selected, out_extended = main._filter_incompatible_layers_by_body_type(
            selected_layers=selected,
            extended_layers=extended,
            scan_result=scan_result,
            requested_body_type="female",
        )
        self.assertIsNone(out_selected.hair)
        self.assertEqual("dress_kimono", out_selected.armor)
        self.assertEqual({}, out_extended)

    def test_lpc_only_fallback_replaces_undead_and_matches_prompt_styles(self) -> None:
        scan_result = {
            "manifest": {
                "body": ["body", "body_zombie"],
                "hair": ["hair_xlong", "hair_high_and_tight"],
                "torso": ["torso_clothes_tshirt", "torso_clothes_robe"],
                "weapons": ["weapon_sword_katana", "weapon_sword_arming"],
            },
            "items_by_id": {
                "body": {
                    "item_id": "body",
                    "primary_category": "body",
                    "search_text": "body light human female",
                    "semantic_tags": ["role.body"],
                    "path_parts": ["body"],
                    "supports_body_types": ["female", "male", "child"],
                    "layer_count": 1,
                },
                "body_zombie": {
                    "item_id": "body_zombie",
                    "primary_category": "body",
                    "search_text": "body zombie undead",
                    "semantic_tags": ["role.body"],
                    "path_parts": ["body", "special"],
                    "supports_body_types": ["female", "male"],
                    "layer_count": 1,
                },
                "hair_xlong": {
                    "item_id": "hair_xlong",
                    "primary_category": "hair",
                    "search_text": "hair xlong blonde female",
                    "semantic_tags": ["role.hair"],
                    "path_parts": ["hair", "long"],
                    "supports_body_types": ["female", "male"],
                    "layer_count": 1,
                },
                "hair_high_and_tight": {
                    "item_id": "hair_high_and_tight",
                    "primary_category": "hair",
                    "search_text": "hair high and tight short",
                    "semantic_tags": ["role.hair"],
                    "path_parts": ["hair", "bald"],
                    "supports_body_types": ["female", "male"],
                    "layer_count": 1,
                },
                "torso_clothes_tshirt": {
                    "item_id": "torso_clothes_tshirt",
                    "primary_category": "armor",
                    "search_text": "torso clothes tshirt blue shirt",
                    "semantic_tags": ["role.outfit", "type.clothes"],
                    "path_parts": ["torso", "shirts"],
                    "supports_body_types": ["female", "male"],
                    "layer_count": 1,
                    "type_name": "clothes",
                },
                "torso_clothes_robe": {
                    "item_id": "torso_clothes_robe",
                    "primary_category": "armor",
                    "search_text": "torso clothes robe black",
                    "semantic_tags": ["role.outfit", "type.clothes"],
                    "path_parts": ["torso", "shirts"],
                    "supports_body_types": ["female", "male"],
                    "layer_count": 1,
                    "type_name": "clothes",
                },
                "weapon_sword_katana": {
                    "item_id": "weapon_sword_katana",
                    "primary_category": "weapons",
                    "search_text": "weapon sword katana samurai",
                    "semantic_tags": ["weapon.sword", "weapon.melee"],
                    "path_parts": ["weapons", "sword"],
                    "supports_body_types": [],
                    "layer_count": 1,
                },
                "weapon_sword_arming": {
                    "item_id": "weapon_sword_arming",
                    "primary_category": "weapons",
                    "search_text": "weapon sword arming",
                    "semantic_tags": ["weapon.sword", "weapon.melee"],
                    "path_parts": ["weapons", "sword"],
                    "supports_body_types": [],
                    "layer_count": 1,
                },
            },
        }
        out = main._apply_lpc_only_fallback(
            validated_layers=main.SelectedLayers(
                body="body_zombie",
                hair="hair_high_and_tight",
                armor="torso_clothes_robe",
                weapons="weapon_sword_arming",
            ),
            prompt_text="金色头发，上身蓝色T恤，年轻白人女性，拿武士刀",
            scan_result=scan_result,
        )
        self.assertEqual("body", out.body)
        self.assertEqual("hair_xlong", out.hair)
        self.assertEqual("torso_clothes_tshirt", out.armor)
        self.assertEqual("weapon_sword_katana", out.weapons)

    def test_lpc_only_extended_fallback_selects_feet_on_shoe_prompt(self) -> None:
        scan_result = scanner.scan_sheet_definitions(
            scanner.DEFAULT_DEFINITIONS_ROOT,
            scanner.DEFAULT_SPRITES_ROOT,
        )
        with patch(
            "main.load_relay_config",
            return_value=SimpleNamespace(
                runtime=SimpleNamespace(
                    gen_mode_default=False,
                    max_generation_tasks=2,
                    lpc_only_exclude_custom=True,
                )
            ),
        ):
            out = main._apply_lpc_only_extended_fallback(
                validated_extended_layers={},
                prompt_text="年轻女性，红色帆布鞋",
                scan_result=scan_result,
            )
        self.assertIn("feet", out)
        self.assertTrue(out["feet"].startswith("feet_"))

    def test_register_generated_blocks_image_when_gen_off(self) -> None:
        payload = main.RegisterGeneratedAssetRequest(
            category="weapons",
            internal_name="test_blade",
            spritesheet_root="ai_generated/weapons/test_blade",
            image_base64="ZGF0YQ==",
        )
        with self.assertRaises(HTTPException) as cm:
            main._register_generated_asset_core(payload, gen_mode_enabled=False)
        self.assertEqual(422, cm.exception.status_code)

    def test_analyze_lpc_only_returns_502_when_llm_unavailable(self) -> None:
        with patch("main.call_gemini_relay", side_effect=HTTPException(status_code=502, detail="relay down")):
            client = TestClient(main.app)
            response = client.post(
                "/ai/analyze",
                json={"prompt": "一个战士", "gen_mode": False},
            )
        self.assertEqual(502, response.status_code)
        self.assertIn("relay down", str(response.json()))


class ExecuteFlowTests(unittest.TestCase):
    def test_ai_execute_partial_success(self) -> None:
        analysis_before = main.AnalyzeResponse(
            mode_resolved="GEN",
            character_summary="before",
            selected_layers=main.SelectedLayers(
                body="body",
                hair="hair_single",
                armor="torso_armour_plate",
                weapons="weapon_sword_longsword",
            ),
            generation_tasks=[],
            missing_assets=[
                main.MissingAsset(
                    category="weapons",
                    internal_name="nunchuck_alpha",
                    visual_prompt="task_one",
                ),
                main.MissingAsset(
                    category="weapons",
                    internal_name="nunchuck_beta",
                    visual_prompt="task_two",
                ),
            ],
            is_complete=False,
            manifest_refreshed_at="2026-03-31T00:00:00+00:00",
            warnings_count=0,
        )
        analysis_after = main.AnalyzeResponse(
            mode_resolved="GEN",
            character_summary="after",
            selected_layers=analysis_before.selected_layers,
            generation_tasks=[],
            missing_assets=[],
            is_complete=True,
            manifest_refreshed_at="2026-03-31T00:00:00+00:00",
            warnings_count=0,
        )

        def _fake_image(prompt: str, *, size: str = "1:1", n: int = 1) -> str:
            if prompt == "task_one":
                return "ZGF0YQ=="
            raise ValueError("filtered by provider")

        fake_register = main.RegisterGeneratedAssetResponse(
            definition_file="/tmp/fake.json",
            template_used="weapon_sword_longsword",
            selection_reason="similarity_match",
            precheck=main.PrecheckResult(png_count=1, animation_hint_matched=True),
            single_image_processed=True,
            generated_png_files=1,
            metadata_rebuilt=True,
            backup_files=[],
            manifest_updated=True,
        )

        with (
            patch("main.resolve_gen_mode", return_value=True),
            patch("main._run_analyze", side_effect=[analysis_before, analysis_after]),
            patch("main.call_image_relay", side_effect=_fake_image),
            patch("main._register_generated_asset_core", return_value=fake_register),
        ):
            client = TestClient(main.app)
            response = client.post(
                "/ai/execute",
                json={
                    "prompt": "warrior with nunchucks",
                    "gen_mode": True,
                    "max_generation_tasks": 2,
                    "auto_register": True,
                },
            )
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("partial_success", payload["overall_status"])
        self.assertEqual(2, len(payload["generated_assets"]))
        self.assertEqual("succeeded", payload["generated_assets"][0]["image_status"])
        self.assertEqual("failed", payload["generated_assets"][1]["image_status"])
        self.assertGreaterEqual(len(payload["errors"]), 1)


class StaticRouteTests(unittest.TestCase):
    def test_generator_index_is_served(self) -> None:
        client = TestClient(main.app)
        response = client.get("/generator/index.html")
        expected_status = 200 if main.GENERATOR_DIR.exists() else 503
        self.assertEqual(expected_status, response.status_code)

    def test_capability_report_endpoint(self) -> None:
        client = TestClient(main.app)
        response = client.get("/assets/capability-report")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertIn("summary", payload)
        self.assertIn("core_category_counts", payload)


if __name__ == "__main__":
    unittest.main()
