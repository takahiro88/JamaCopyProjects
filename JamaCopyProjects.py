# 2026.03.05 Copy project items and relations from JSON files to another Jama instance
# Need to set environment variables before running this script.
# set  AUTH_TYPE=BASIC or set  AUTH_TYPE=OAUTH
# set  JAMA_URL=https://your-target-jama-instance.com
# set  JAMA_USERNAME=your_username  (Only for BASIC auth)
# set  JAMA_PASSWORD=your_password  (Only for BASIC auth)
# if auth type is not BASIC, then set the following environment variables instead of above 3 variables.
# set JAMA_CLIENT_ID=XXX
# set JAMA_CLIENT_SECRET=XXX

# Usage: python JamaCopyProject.py
# Example: python JamaCopyProject.py
# The script will automatically scan copy_from folder for project files

from asyncio.log import logger
import time
import sys
import os
import json
import re
import urllib.parse
from datetime import datetime, date, timedelta
from py_jama_rest_client.client import JamaClient
from collections import OrderedDict

import urllib

class TeeOutput:
    """
    標準出力とファイルの両方に出力するためのクラス
    """
    def __init__(self, log_file):
        self.terminal = sys.stdout
        self.log_file = log_file

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

class JamaProjectCopier(JamaClient):

    def __init__(self):
        print('Started JamaProjectCopier')
        now = datetime.now()
        print(now)
        
        AUTH_TYPE = os.environ.get('AUTH_TYPE')

        if AUTH_TYPE == 'BASIC':
            import urllib3
            from urllib3.exceptions import InsecureRequestWarning
            urllib3.disable_warnings(InsecureRequestWarning)

            print('Using BASIC authentication')
            
            JAMA_URL = os.environ.get('JAMA_URL').rstrip('/')
            CREDENTIALS = (os.environ.get('JAMA_USERNAME'), os.environ.get('JAMA_PASSWORD'))
            super().__init__(JAMA_URL, credentials=CREDENTIALS, verify=False, allowed_results_per_page=50)

        else:
            print('Using OAUTH authentication')
            JAMA_URL = os.environ.get('JAMA_URL').rstrip('/')
            # 認証情報は環境変数にある前提
            CREDENTIALS = (os.environ.get('JAMA_CLIENT_ID'), os.environ.get('JAMA_CLIENT_SECRET')) 
            super().__init__(JAMA_URL, credentials=CREDENTIALS, oauth=True)
        self.JAMA_URL = JAMA_URL
        self.target_item_types_cache = None

    def print_error(self, message):
        """
        エラーメッセージを赤色で表示する
        """
        print(f"\033[91m{message}\033[0m")

    def print_warning(self, message):
        """
        警告メッセージを黄色で表示する
        """
        print(f"\033[93m{message}\033[0m")

    def scan_copy_from_projects(self):
        """
        copy_fromフォルダをスキャンして利用可能なプロジェクトIDを検出する
        """
        copy_from_dir = "copy_from\\project_setting"
        if not os.path.exists(copy_from_dir):
            self.print_error(f"Error: {copy_from_dir} directory does not exist.")
            return []

        project_ids = set()
        
        # copy_fromフォルダ内のファイルをスキャン
        for filename in os.listdir(copy_from_dir):
            if filename.startswith("project_") and filename.endswith(".json"):
                # project_204.json or project_204_items.json or project_204_relations.json
                parts = filename.replace(".json", "").split("_")
                if len(parts) >= 2:
                    try:
                        project_id = int(parts[1])
                        project_ids.add(project_id)
                    except ValueError:
                        continue
        
        available_projects = []
        for project_id in sorted(project_ids):
            # 必要な3つのファイルが存在するかチェック
            project_file = os.path.join(copy_from_dir, f"project_{project_id}.json")
            items_file = os.path.join(copy_from_dir, f"project_{project_id}_items.json")
            relations_file = os.path.join(copy_from_dir, f"project_{project_id}_relations.json")
            
            if all(os.path.exists(f) for f in [project_file, items_file, relations_file]):
                available_projects.append(project_id)
                print(f"Found complete project files for ID: {project_id}")
            else:
                missing = []
                if not os.path.exists(project_file): missing.append("project info")
                if not os.path.exists(items_file): missing.append("items")
                if not os.path.exists(relations_file): missing.append("relations")
                print(f"Incomplete project files for ID {project_id}, missing: {', '.join(missing)}")
        
        return available_projects

    def get_target_picklists(self):
        """
        コピー先のpicklist情報を取得し、optionsも合わせて取得する
        """
        try:
            target_picklists = list(self.get_pick_lists())
            
            # picklist IDでインデックシングした辞書を作成
            target_picklists_by_id = {}
            for picklist in target_picklists:
                picklist_id = picklist.get('id')
                if picklist_id:
                    try:
                        # picklist optionsを取得
                        picklist_options = list(self.get_pick_list_options(picklist_id))
                        target_picklists_by_id[picklist_id] = {
                            'info': picklist,
                            'options': picklist_options
                        }
                    except Exception as e:
                        self.print_warning(f"Warning: Could not get options for picklist {picklist_id}: {str(e)}")
                        target_picklists_by_id[picklist_id] = {
                            'info': picklist,
                            'options': []
                        }
            
            print(f"Found {len(target_picklists_by_id)} target pick lists")
            return target_picklists_by_id
            
        except Exception as e:
            self.print_error(f"Error getting target pick lists: {str(e)}")
            return {}

    def create_picklist_mappings(self, source_picklists_by_id, target_picklists_by_id):
        """
        sourceとtargetのpicklistとpicklist optionsのマッピングを作成する
        名前ベースでマッチングを行う
        """
        picklist_id_mapping = {}  # source_picklist_id: target_picklist_id
        picklist_option_mapping = {}  # source_option_id: target_option_id
        
        print(f"\n=== Creating PickList Mappings ===")
        
        for source_picklist_id, source_data in source_picklists_by_id.items():
            source_picklist = source_data['info']
            source_options = source_data['options']
            source_name = source_picklist.get('name', '')
            
            # 名前でマッチするtarget picklistを探す
            target_picklist_id = None
            target_options = []
            
            for target_id, target_data in target_picklists_by_id.items():
                target_picklist = target_data['info']
                target_name = target_picklist.get('name', '')
                if source_name == target_name:
                    target_picklist_id = target_id
                    target_options = target_data['options']
                    break
            
            if target_picklist_id:
                picklist_id_mapping[source_picklist_id] = target_picklist_id
                print(f"PickList mapping: '{source_name}' (source ID: {source_picklist_id} -> target ID: {target_picklist_id})")
                
                # picklist optionsをマッピング
                target_options_by_name = {opt.get('name', ''): opt for opt in target_options}
                
                for source_option in source_options:
                    source_option_id = source_option.get('id')
                    source_option_name = source_option.get('name', '')
                    
                    if source_option_name in target_options_by_name:
                        target_option = target_options_by_name[source_option_name]
                        target_option_id = target_option.get('id')
                        picklist_option_mapping[source_option_id] = target_option_id
                        print(f"  Option mapping: '{source_option_name}' (source ID: {source_option_id} -> target ID: {target_option_id})")
                    else:
                        # マッチするオプションがない場合、オプションを)作成
                        description = source_option.get('description', '')
                        sort_order = source_option.get('sortOrder', 0)
                        default = source_option.get('default', False)
                        option_id = source_option.get('id')
                        value = source_option.get('value')
                        if value == "":
                            value = None
                        color = source_option.get('color')
                        if color == "":
                            color = None

                        try:
                            tgt_id = self.post_picklist_option(target_picklist_id, source_option_name, description, sort_order, default, value, color)
                            picklist_option_mapping[option_id] = tgt_id

                        except Exception as e:
                            #オプション作成に失敗したらデフォルトに集約
                            default_option = next((opt for opt in target_options if opt.get('default', False)), None)
                            if default_option:
                                target_option_id = default_option.get('id')
                                picklist_option_mapping[source_option_id] = target_option_id
                                self.print_warning(f"  Option fallback: '{source_option_name}' (source ID: {source_option_id}) -> target ID '{default_option.get('name', '')}' (target ID: {target_option_id})")
                            else:
                                self.print_warning(f"  No mapping found for option '{source_option_name}' (source ID: {source_option_id})")
            else:
                try:
                    new_picklist = self.post_picklist(name=source_name, description=source_picklist.get('description', ''))
                    for opt in source_options:
                        if opt['name'] != "Unassigned":
                            name = opt['name']
                            description = opt.get('description', '')
                            sort_order = opt.get('sortOrder', 0)
                            default = opt.get('default', False)
                            option_id = opt.get('id')
                            value = opt.get('value')
                            if value == "":
                                value = None
                            color = opt.get('color')
                            if color == "":
                                color = None
                            tgt_id = self.post_picklist_option(new_picklist, name, description, sort_order, default, value, color)
                            picklist_option_mapping[option_id] = tgt_id

                    print(f"Created picklist: {source_name} (source ID: {source_picklist_id} -> new ID: {new_picklist})")
                    picklist_id_mapping[source_picklist_id] = new_picklist

                except Exception as e:
                    self.print_error(f"Failed to create picklist '{source_name}' for source ID {source_picklist_id}: {str(e)}")
                    continue

        print(f"Created {len(picklist_id_mapping)} picklist mappings and {len(picklist_option_mapping)} option mappings")
        return picklist_id_mapping, picklist_option_mapping

    def load_source_picklists(self):
        """
        copy_from/pick_list.jsonからコピー元のpicklist情報を読み込み、
        それぞれのpicklistのoptionsも合わせて読み込む
        """
        copy_from_dir = "copy_from"
        picklist_file = os.path.join(copy_from_dir, "pick_lists.json")
        
        if not os.path.exists(picklist_file):
            self.print_error(f"{picklist_file} does not exist. Cannot map pick lists.")
            raise Exception(f"Missing required file: {picklist_file}")
            return {}
        
        try:
            with open(picklist_file, 'r', encoding='utf-8') as f:
                source_picklists = json.load(f)
            
            # picklist IDでインデックシングした辞書を作成
            source_picklists_by_id = {}
            for picklist in source_picklists:
                picklist_id = picklist.get('id')
                if picklist_id:
                    # それぞれのpicklistのoptionsも読み込む
                    options_file = os.path.join(copy_from_dir, f"pick_list_{picklist_id}_options.json")
                    piocklist_options = []
                    if os.path.exists(options_file):
                        with open(options_file, 'r', encoding='utf-8') as f:
                            piocklist_options = json.load(f)
                    
                    source_picklists_by_id[picklist_id] = {
                        'info': picklist,
                        'options': piocklist_options
                    }
            
            print(f"Loaded {len(source_picklists_by_id)} source pick lists with options")
            return source_picklists_by_id
            
        except Exception as e:
            self.print_error(f"Error loading source pick lists from {picklist_file}: {str(e)}")
            return {}

    def load_source_item_types(self):
        """
        copy_from/project_itemtypes.jsonからコピー元のitem type情報を読み込む
        """
        copy_from_dir = "copy_from"
        itemtypes_file = os.path.join(copy_from_dir, "project_itemtypes.json")
        
        if not os.path.exists(itemtypes_file):
            print(f"Warning: {itemtypes_file} does not exist. Cannot map item types.")
            return {}
        
        try:
            with open(itemtypes_file, 'r', encoding='utf-8') as f:
                source_item_types = json.load(f)
            
            # typeKeyでインデックシングした辞書を作成
            source_types_by_key = {}
            for item_type in source_item_types:
                type_key = item_type.get('typeKey', '')
                if type_key:
                    source_types_by_key[type_key] = item_type
            
            print(f"Loaded {len(source_types_by_key)} source item types from {itemtypes_file}")
            return source_types_by_key
            
        except Exception as e:
            self.print_error(f"Error loading source item types from {itemtypes_file}: {str(e)}")
            return {}

    def get_target_item_types(self):
        """
        コピー先プロジェクトぎitem type情報を取得する
        """
        try:
            self.target_item_types_cache = self.get_item_types()
            target_item_types = list(self.target_item_types_cache)
            
            # typeKeyでインデックシングした辞書を作成
            target_types_by_key = {}
            for item_type in target_item_types:
                type_key = item_type.get('typeKey', '')
                if type_key:
                    target_types_by_key[type_key] = item_type
            
            print(f"Found {len(target_types_by_key)} target item types")
            return target_types_by_key
            
        except Exception as e:
            self.print_error(f"Error getting target item types: {str(e)}")
            return {}

    def create_missing_item_types(self, source_types_by_key, target_types_by_key):
        """
        不足しているitem typeを作成し、typeIDのマッピングを作成する
        """
        type_id_mapping = {}  # source_type_id: target_type_id
        created_types = []
        
        for type_key, source_type in source_types_by_key.items():
            source_type_id = source_type.get('id')
            
            if type_key in target_types_by_key:
                # 既存のitem typeが存在する場合
                target_type_id = target_types_by_key[type_key]['id']
                type_id_mapping[source_type_id] = target_type_id
                print(f"Item type '{type_key}': source ID {source_type_id} -> target ID {target_type_id} (existing)")
            else:
                # item typeが存在しない場合、作成する
                try:
                    display = source_type.get('display', type_key).strip()
                    display_plural = source_type.get('displayPlural', display + 's').strip()
                    description = source_type.get('description', '').strip()
                    widgets = source_type.get('widgets')
                    category = source_type.get('category')
                    
                    # imageパラメータの処理：URLの最後のファイル名部分（拡張子を除く）を大文字にする
                    image = None
                    image_url = source_type.get('image', '')
                    if image_url:
                        # URLから最後のファイル名部分を取得
                        filename = os.path.basename(image_url.split('?')[0])  # クエリパラメータも除去
                        if filename and '.' in filename:
                            # 拡張子を除いてファイル名を取得し、大文字に変換
                            image = os.path.splitext(filename)[0].upper()
                            # 特例: PAGE_WHITE_STACKをPAGE_STACKに変換
                            if image == 'PAGE_WHITE_STACK':
                                image = 'PAGE_STACK'
                    
                    print(f"Creating item type '{type_key}' - display: '{display}', displayPlural: '{display_plural}', image: {image}, category: {category}")
                    
                    created_with_default = False  # デフォルト画像でのリトライフラグ
                    
                    # 新しいitem typeを作成（リトライ機能付き）
                    try:
                        new_type_id = self.post_item_type(
                            key=type_key,
                            display=display,
                            displayPlural=display_plural,
                            description=description,
                            image=image,
                            widgets=widgets,
                            category=category
                        )
                    except Exception as e:
                        # imageが原因と思われる場合、デフォルト画像でリトライ
                        self.print_warning(f"Failed to create item type '{type_key}' with image '{image}': {str(e)}")
                        self.print_warning(f"Retrying with default image 'WEBSITE_BLUE'...")
                        
                        try:
                            new_type_id = self.post_item_type(
                                key=type_key,
                                display=display,
                                displayPlural=display_plural,
                                description=description,
                                image='WEBSITE_BLUE',
                                widgets=widgets,
                                category=category
                            )
                            created_with_default = True
                        except Exception as e2:
                            self.print_error(f"Critical Error: Failed to create item type '{type_key}' even with default image 'WEBSITE_BLUE': {str(e2)}")
                            self.print_error(f"Original error: {str(e)}")
                            self.print_error("Cannot continue project copying without essential item types. Aborting operation.")
                            raise Exception(f"Fatal error creating item type '{type_key}': Both original and default image creation failed")
                    
                    type_id_mapping[source_type_id] = new_type_id
                    created_types.append({
                        'type_key': type_key,
                        'source_id': source_type_id,
                        'new_id': new_type_id,
                        'used_default_image': created_with_default
                    })
                    
                    if created_with_default:
                        print(f"Created item type '{type_key}' with default image: source ID {source_type_id} -> new ID {new_type_id}")
                    else:
                        print(f"Created item type '{type_key}': source ID {source_type_id} -> new ID {new_type_id}")
                    
                except Exception as e:
                    self.print_error(f"Critical Error: Failed to create item type '{type_key}': {str(e)}")
                    self.print_error("Cannot continue project copying without essential item types. Aborting operation.")
                    raise
        
        print(f"Item type mapping completed. Created {len(created_types)} new types.")
        return type_id_mapping, created_types

    def synchronize_item_type_fields(self, source_types_by_key, target_types_by_key, type_id_mapping, picklist_id_mapping=None):
        """
        sourceとtargetのitemtypeのfieldsを比較し、sourceにあってtargetにないfieldを追加する
        picklist_id_mapping: picklistのIDマッピング（sourceのpicklistIDをtargetのIDに変換）
        """
        print(f"🔄 Synchronizing fields for {len(source_types_by_key)} item types...")
        
        for type_key, source_type in source_types_by_key.items():
            if type_key not in target_types_by_key:
                print(f"⏭️  Skipping {type_key} (new type, no field sync needed)")
                continue
                
            target_type = target_types_by_key[type_key]
            source_fields = source_type.get('fields', [])
            target_fields = target_type.get('fields', [])
            
            # targetのfieldsを名前でインデックス化（$を含む場合はベース名で比較）
            target_fields_by_name = {}
            target_base_names = {}  # ベース名でのインデックス
            for field in target_fields:
                field_name = field.get('name', '')
                if field_name:
                    target_fields_by_name[field_name] = field
                    # $を含む場合はベース名でもインデックス化
                    if '$' in field_name:
                        base_name = field_name.split('$')[0]
                        target_base_names[base_name] = field
                    else:
                        target_base_names[field_name] = field
            
            # sourceのfieldsを確認し、targetにないものを探す（$ベース名で比較）
            missing_fields = []
            for source_field in source_fields:
                source_field_name = source_field.get('name', '')
                if source_field_name:
                    # $を含む場合はベース名で比較
                    if '$' in source_field_name:
                        source_base_name = source_field_name.split('$')[0]
                        if source_base_name not in target_base_names:
                            missing_fields.append(source_field)
                        else:
                            print(f"  🔍 Field '{source_field_name}' matches target field with base name '{source_base_name}'")
                    else:
                        # 通常のfield name
                        if source_field_name not in target_base_names:
                            missing_fields.append(source_field)
                        else:
                            print(f"  🔍 Field '{source_field_name}' already exists in target")
            
            if missing_fields:
                print(f"📋 Item type '{type_key}': Found {len(missing_fields)} missing field(s)")
                target_type_id = target_type.get('id')
                
                for missing_field in missing_fields:
                    field_name = missing_field.get('name', 'Unknown')
                    field_type = missing_field.get('fieldType', 'STRING')
                    
                    try:
                        print(f"  ➕ Adding field '{field_name}' (type: {field_type}) to target item type {target_type_id}")
                        
                        # post_item_type_fieldを呼び出してfieldを追加
                        original_field_name = missing_field.get('name', '')
                        
                        # itemType固有のfield_nameの処理
                        # Jamaの仕様: {name}${itemTypeID} 形式だが、postする際は{name}部分のみ指定
                        if '$' in original_field_name:
                            # field_nameから$以降を除去: {field_name}${item_type_id} -> {field_name}
                            field_base_name = original_field_name.split('$')[0]
                            print(f"    🔄 ItemType-specific field detected: '{original_field_name}' -> using base name '{field_base_name}' for creation")
                            field_name = field_base_name
                        else:
                            # '$' が含まれていない通常のfield_name
                            field_name = original_field_name
                        
                        field_label = missing_field.get('label', field_name)
                        field_type = missing_field.get('fieldType', 'STRING')
                        readonly = missing_field.get('readOnly', False)
                        readOnlyAllowApiOverwrite = missing_field.get('readOnlyAllowApiOverwrite', False)
                        required = missing_field.get('required', False)
                        triggersuspect = missing_field.get('triggersuspect', False)
                        source_picklist_id = missing_field.get('pickList')
                        text_type = missing_field.get('textType')
                        
                        # PickListマッピングの適用
                        picklist_id = None
                        if source_picklist_id and picklist_id_mapping:
                            if source_picklist_id in picklist_id_mapping:
                                picklist_id = picklist_id_mapping[source_picklist_id]
                                print(f"    🔄 Mapping picklist: {source_picklist_id} -> {picklist_id}")
                            else:
                                print(f"    ⚠️ PickList {source_picklist_id} not found in mapping, creating field without picklist")
                                picklist_id = None
                        elif source_picklist_id:
                            print(f"    ⚠️ PickList mapping not available, creating field without picklist")
                            picklist_id = None
                        if field_type == 'CALCULATED':
                            field_type = 'INTEGER'
                        if field_type == 'ROLLUP':
                            continue
                        self.post_item_type_field(
                            item_type_id=target_type_id,
                            name=field_name,
                            label=field_label,
                            field_type=field_type,
                            readOnly=readonly,
                            readOnlyAllowApiOverwrite=readOnlyAllowApiOverwrite,
                            required=required,
                            triggersuspect=triggersuspect,
                            picklist=picklist_id,
                            textType=text_type
                        )
                        print(f"  ✅ Successfully added field '{field_name}'")
                        
                    except Exception as e:
                        print(f"  ❌ Failed to add field '{field_name}': {str(e)}")
                        # 継続して他のfieldも処理
                        continue
            else:
                print(f"✅ Item type '{type_key}': All fields already exist")
        
        print(f"🔄 Field synchronization completed")

    def load_source_relationship_types(self):
        """
        copy_from/relationshiptypes.jsonからコピー元のrelationship type情報を読み込む
        """
        copy_from_dir = "copy_from"
        relationshiptypes_file = os.path.join(copy_from_dir, "relationshiptypes.json")
        
        if not os.path.exists(relationshiptypes_file):
            self.print_warning(f"Warning: {relationshiptypes_file} does not exist. Cannot validate relationship types.")
            return {}
        
        try:
            with open(relationshiptypes_file, 'r', encoding='utf-8') as f:
                source_relationship_types = json.load(f)
            
            # typeKeyでインデックシングした辞書を作成
            source_types_by_key = {}
            for rel_type in source_relationship_types:
                type_key = rel_type.get('id', '')
                if type_key:
                    source_types_by_key[type_key] = rel_type
            
            print(f"Loaded {len(source_types_by_key)} source relationship types from {relationshiptypes_file}")
            return source_types_by_key
            
        except Exception as e:
            self.print_error(f"Error loading source relationship types from {relationshiptypes_file}: {str(e)}")
            return {}

    def get_target_relationship_types(self):
        """
        コピー先のrelationship type情報を取得する
        """
        try:
            target_relationship_types = list(self.get_relationship_types())
            
            # typeKeyでインデックシングした辞書を作成
            target_types_by_key = {}
            for rel_type in target_relationship_types:
                type_key = rel_type.get('id', '')
                if type_key:
                    target_types_by_key[type_key] = rel_type
            
            print(f"Found {len(target_types_by_key)} target relationship types")
            return target_types_by_key, target_relationship_types
            
        except Exception as e:
            self.print_error(f"Error getting target relationship types: {str(e)}")
            return {}, []

    def validate_relationship_types(self):
        """
        コピー元とコピー先のrelationship typesを比較し、差異がある場合は自動マッピングの選択肢を提供する
        戻り値: (success: bool, type_mapping: dict)
        """
        print("\n=== Relationship Type Validation ===")
        
        # コピー元のrelationship typesを読み込み
        source_types_by_key = self.load_source_relationship_types()
        if not source_types_by_key:
            self.print_warning("No source relationship types found. Skipping validation.")
            return True, {}
        
        # コピー先のrelationship typesを取得
        target_types_by_key, target_relationship_types = self.get_target_relationship_types()
        if not target_types_by_key:
            self.print_error("Failed to get target relationship types. Cannot validate.")
            return False, {}
        
        # 差異をチェック
        missing_types = []
        different_types = []
        exact_matches = []
        
        for type_key, source_type in source_types_by_key.items():
            if type_key not in target_types_by_key:
                missing_types.append({
                    'source_id': type_key,
                    'source_name': source_type.get('name', ''),
                    'source_type': source_type.get('type', '')
                })
            else:
                # 名前や色などの基本属性を比較
                target_type = target_types_by_key[type_key]
                source_name = source_type.get('name', '')
                target_name = target_type.get('name', '')
                source_type_value = source_type.get('type', '')
                target_type_value = target_type.get('type', '')
                
                if source_name != target_name or source_type_value != target_type_value:
                    different_types.append({
                        'id': type_key,
                        'source_name': source_name,
                        'target_name': target_name,
                        'source_type': source_type_value,
                        'target_type': target_type_value
                    })
                else:
                    exact_matches.append({
                        'id': type_key,
                        'name': source_name
                    })

        # 結果の表示
        if not missing_types and not different_types:
            print("✓ All relationship types match between source and target.")
            # 完全一致の場合の1:1マッピングを作成
            type_mapping = {type_info['id']: type_info['id'] for type_info in exact_matches}
            return True, type_mapping
        
        print(f"Found relationship type differences:")
        if exact_matches:
            print(f"✓ Exact matches: {len(exact_matches)}")
        if missing_types:
            print(f"✗ Missing types in target: {len(missing_types)}")
            for missing in missing_types:
                print(f"  - {missing['source_id']}: '{missing['source_name']}' (type: {missing['source_type']})")
        if different_types:
            print(f"⚠ Different attributes: {len(different_types)}")
            for diff in different_types:
                print(f"  - {diff['id']}: '{diff['source_name']}' vs '{diff['target_name']}' (type: {diff['source_type']} vs {diff['target_type']})")

        # 自動マッピングを実行
        print("\n=== Auto-mapping Relationship Types ===")
        type_mapping = self._create_automatic_mapping(
            source_types_by_key, target_types_by_key, 
            exact_matches, missing_types, different_types
        )
        return True, type_mapping

    def _save_target_relationship_types(self, target_relationship_types):
        """
        コピー先のrelationship typesをJSONファイルに保存
        """
        try:
            os.makedirs("output", exist_ok=True)
            output_filename = f".\\output\\dest_relationshiptypes.json"
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(target_relationship_types, f, indent=4, sort_keys=True, separators=(',', ': '), ensure_ascii=False)
            print(f"Target relationship types saved to {output_filename}")
        except Exception as e:
            self.print_error(f"Failed to save target relationship types: {str(e)}")

    def _create_automatic_mapping(self, source_types_by_key, target_types_by_key, exact_matches, missing_types, different_types):
        """
        自動マッピングロジックを実行
        """
        type_mapping = {}
        mapping_log = []
        
        # 1. 完全一致のマッピング
        for match in exact_matches:
            type_mapping[match['id']] = match['id']
            mapping_log.append({
                'source_id': match['id'],
                'target_id': match['id'],
                'source_name': match['name'],
                'target_name': match['name'],
                'mapping_type': 'exact_match'
            })

        # 2. 属性が異なるが同じIDのものはそのまま使用（警告付き）
        for diff in different_types:
            type_mapping[diff['id']] = diff['id']
            mapping_log.append({
                'source_id': diff['id'],
                'target_id': diff['id'],
                'source_name': diff['source_name'],
                'target_name': diff['target_name'],
                'mapping_type': 'forced_match',
                'warning': f"Different attributes: '{diff['source_name']}' vs '{diff['target_name']}'"
            })

        # 3. 不足しているタイプは名前の類似性で最適なターゲットを探す
        available_targets = [{'id': k, 'name': v.get('name', ''), 'type': v.get('type', '')} 
                           for k, v in target_types_by_key.items() 
                           if k not in type_mapping.values()]
        
        for missing in missing_types:
            best_match = self._find_best_match(missing, available_targets)
            
            if best_match:
                type_mapping[missing['source_id']] = best_match['id']
                available_targets.remove(best_match)  # 一度使ったターゲットは除外
                mapping_log.append({
                    'source_id': missing['source_id'],
                    'target_id': best_match['id'],
                    'source_name': missing['source_name'],
                    'target_name': best_match['name'],
                    'mapping_type': 'best_guess',
                    'warning': 'Auto-mapped based on name similarity - please verify'
                })
            else:
                # マッチするものがない場合、最初の利用可能なタイプを使用
                if available_targets:
                    fallback_target = available_targets[0]
                    type_mapping[missing['source_id']] = fallback_target['id']
                    available_targets.remove(fallback_target)
                    mapping_log.append({
                        'source_id': missing['source_id'],
                        'target_id': fallback_target['id'],
                        'source_name': missing['source_name'],
                        'target_name': fallback_target['name'],
                        'mapping_type': 'fallback',
                        'warning': 'No good match found - using fallback mapping'
                    })

        # マッピング結果をログ出力
        print("\n=== Relationship Type Mapping Results ===")
        for log_entry in mapping_log:
            mapping_type = log_entry['mapping_type']
            warning = log_entry.get('warning', '')
            
            if mapping_type == 'exact_match':
                print(f"✓ {log_entry['source_id']}: '{log_entry['source_name']}' -> '{log_entry['target_name']}'")
            elif mapping_type == 'forced_match':
                print(f"⚠ {log_entry['source_id']}: '{log_entry['source_name']}' -> '{log_entry['target_name']}' (FORCED - {warning})")
            elif mapping_type == 'best_guess':
                print(f"🔄 {log_entry['source_id']}: '{log_entry['source_name']}' -> '{log_entry['target_name']}' (AUTO-MAPPED - {warning})")
            elif mapping_type == 'fallback':
                print(f"❓ {log_entry['source_id']}: '{log_entry['source_name']}' -> '{log_entry['target_name']}' (FALLBACK - {warning})")

        # マッピングログをファイルに保存
        try:
            os.makedirs("output", exist_ok=True)
            log_filename = f"output/relationship_mapping_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(log_filename, 'w', encoding='utf-8') as f:
                json.dump(mapping_log, f, indent=4, ensure_ascii=False)
            print(f"\nMapping log saved to {log_filename}")
        except Exception as e:
            self.print_error(f"Failed to save mapping log: {str(e)}")

        return type_mapping

    def _find_best_match(self, missing_type, available_targets):
        """
        名前の類似性に基づいて最適なマッチを見つける
        """
        missing_name = missing_type['source_name'].lower()
        missing_type_value = missing_type['source_type'].lower()
        
        best_score = 0
        best_match = None
        
        for target in available_targets:
            target_name = target['name'].lower()
            target_type_value = target['type'].lower()
            
            # スコア計算（簡単なword matching）
            score = 0
            
            # タイプが一致する場合は高得点
            if missing_type_value == target_type_value:
                score += 50
            
            # 名前の部分一致
            missing_words = missing_name.split()
            target_words = target_name.split()
            
            for missing_word in missing_words:
                for target_word in target_words:
                    if missing_word in target_word or target_word in missing_word:
                        score += 10
            
            # 完全一致の場合は高得点
            if missing_name == target_name:
                score += 100
            
            if score > best_score:
                best_score = score
                best_match = target
        
        # 最低スコア以上の場合のみ返す
        return best_match if best_score >= 10 else None

    def collect_used_types_from_projects(self, project_infos):
        """
        全プロジェクトで実際に使用されているitem typeとrelationship type、およびchildItemTypeを収集
        """
        used_item_types = set()
        used_child_item_types = set()  # childItemTypeも収集
        used_relationship_types = set()
        
        print("\n=== Collecting Used Types from All Projects ===")
        
        for source_project_id, project_info in project_infos.items():
            print(f"Scanning project {source_project_id} ({project_info['name']})...")
            
            # アイテムタイプとchildItemTypeを収集
            items_data, relations_data = self.load_json_data(source_project_id)
            if items_data:
                for item in items_data:
                    item_type = item.get('itemType')
                    if item_type:
                        used_item_types.add(item_type)
                    
                    # childItemTypeも収集（setタイプのアイテムで使用される）
                    child_item_type = item.get('childItemType')
                    if child_item_type:
                        used_child_item_types.add(child_item_type)
            
            # リレーションシップタイプを収集
            if relations_data:
                for relation in relations_data:
                    relationship_type = relation.get('relationshipType')
                    if relationship_type:
                        used_relationship_types.add(relationship_type)
        
        # childItemTypeもused_item_typesに統合（マッピング対象とするため）
        all_used_item_types = used_item_types | used_child_item_types
        
        print(f"📊 Found {len(used_item_types)} unique item types across all projects")
        print(f"📊 Found {len(used_child_item_types)} unique child item types across all projects")
        print(f"📊 Total item types requiring mapping: {len(all_used_item_types)}")
        print(f"📊 Found {len(used_relationship_types)} unique relationship types across all projects")
        
        return all_used_item_types, used_relationship_types

    def create_filtered_type_mappings(self, used_item_types, used_relationship_types):
        """
        使用されているタイプのみを対象にマッピングを作成
        childItemTypeで参照されているタイプも含めてマッピングを作成する
        """
        print("\n=== Creating Filtered Type Mappings ===")
        
        # PickListマッピングの作成（最初に処理）
        print(f"\nProcessing PickList mappings first...")
        source_picklists_by_id = self.load_source_picklists()
        target_picklists_by_id = self.get_target_picklists()
        picklist_id_mapping, picklist_option_mapping = self.create_picklist_mappings(source_picklists_by_id, target_picklists_by_id)
        
        # Item Typeマッピングの作成（picklistマッピング完了後）
        print(f"\nProcessing {len(used_item_types)} used item types (including child item types)...")
        source_types_by_key = self.load_source_item_types()
        target_types_by_key = self.get_target_item_types()
        # 使用されているタイプのみをフィルタリング
        filtered_source_types = {}
        for type_key, source_type in source_types_by_key.items():
            source_type_id = source_type.get('id')
            if source_type_id in used_item_types:
                filtered_source_types[type_key] = source_type
                print(f"📋 Including type {source_type_id} ({type_key}) in mapping")
                
        print(f"🔍 Filtered to {len(filtered_source_types)} actually used item types (including child types)")
        type_id_mapping, created_types = self.create_missing_item_types(filtered_source_types, target_types_by_key)
        
        # フィールド比較・追加処理（picklistマッピング利用可能）
        print(f"\n🔍 Comparing and adding missing fields...")
        self.synchronize_item_type_fields(filtered_source_types, target_types_by_key, type_id_mapping, picklist_id_mapping)
        
        # Relationship Typeマッピングの作成
        print(f"\nProcessing {len(used_relationship_types)} used relationship types...")
        relationship_validation_success, relationship_type_mapping = self.validate_filtered_relationship_types(used_relationship_types)
        
        return type_id_mapping, created_types, relationship_validation_success, relationship_type_mapping, picklist_id_mapping, picklist_option_mapping

    def validate_filtered_relationship_types(self, used_relationship_types):
        """
        使用されているリレーションシップタイプのみを対象に検証
        """
        print("\n=== Filtered Relationship Type Validation ===")
        
        # コピー元のリレーションシップタイプを読み込み
        source_types_by_key = self.load_source_relationship_types()
        if not source_types_by_key:
            self.print_warning("No source relationship types found. Skipping validation.")
            return True, {}
        
        # 使用されているタイプのみをフィルタリング
        filtered_source_types = {k: v for k, v in source_types_by_key.items() if k in used_relationship_types}
        print(f"🔍 Filtered to {len(filtered_source_types)} actually used relationship types")
        
        if not filtered_source_types:
            print("No used relationship types found. Skipping validation.")
            return True, {}
        
        # コピー先のリレーションシップタイプを取得
        target_types_by_key, target_relationship_types = self.get_target_relationship_types()

        if not target_types_by_key:
            self.print_error("Failed to get target relationship types. Cannot validate.")
            return False, {}
        # 一応保存
        self._save_target_relationship_types(target_relationship_types)       
        
        # 差異をチェック（フィルタリングされたタイプのみ）
        missing_types = []
        different_types = []
        exact_matches = []
        
        for type_key, source_type in filtered_source_types.items():
            if type_key not in target_types_by_key:
                missing_types.append({
                    'source_id': type_key,
                    'source_name': source_type.get('name', ''),
                    'source_type': source_type.get('type', '')
                })
            else:
                # 名前や色などの基本属性を比較
                target_type = target_types_by_key[type_key]
                source_name = source_type.get('name', '')
                target_name = target_type.get('name', '')
                source_type_value = source_type.get('type', '')
                target_type_value = target_type.get('type', '')
                
                if source_name != target_name or source_type_value != target_type_value:
                    different_types.append({
                        'id': type_key,
                        'source_name': source_name,
                        'target_name': target_name,
                        'source_type': source_type_value,
                        'target_type': target_type_value
                    })
                else:
                    exact_matches.append({
                        'id': type_key,
                        'name': source_name
                    })

        # 結果の表示
        if not missing_types and not different_types:
            print("✓ All used relationship types match between source and target.")
            # 完全一致の場合の1:1マッピングを作成
            type_mapping = {type_info['id']: type_info['id'] for type_info in exact_matches}
            return True, type_mapping
        
        print(f"Found relationship type differences in used types:")
        if exact_matches:
            print(f"✓ Exact matches: {len(exact_matches)}")
        if missing_types:
            print(f"✗ Missing types in target: {len(missing_types)}")
            for missing in missing_types:
                print(f"  - {missing['source_id']}: '{missing['source_name']}' (type: {missing['source_type']})")
        if different_types:
            print(f"⚠ Different attributes: {len(different_types)}")
            for diff in different_types:
                print(f"  - {diff['id']}: '{diff['source_name']}' vs '{diff['target_name']}' (type: {diff['source_type']} vs {diff['target_type']})")

        # 自動マッピングを実行
        print("\n=== Auto-mapping Used Relationship Types ===")
        type_mapping = self._create_automatic_mapping(
            filtered_source_types, target_types_by_key, 
            exact_matches, missing_types, different_types
        )
        return True, type_mapping

    def load_project_info(self, project_id):
        """
        project_XXX.jsonファイルからプロジェクト情報を読み込む
        フォルダ構造情報（isFolder, parent）も含む
        """
        copy_from_dir = "copy_from\\project_setting"
        project_file = os.path.join(copy_from_dir, f"project_{project_id}.json")
        
        if not os.path.exists(project_file):
            self.print_error(f"Error: {project_file} does not exist.")
            return None, None, None, None
        
        try:
            with open(project_file, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            fields = project_data.get('fields', {})
            project_name = fields.get('name', f'Project_{project_id}')
            project_key = fields.get('projectKey')
            
            is_folder = project_data.get('isFolder', False)
            parent_id = project_data.get('parent')
            
            folder_status = "📁 PROJECT FOLDER" if is_folder else "📄 PROJECT"
            print(f"{folder_status} {project_id}: name='{project_name}', key='{project_key}'")
            
            if parent_id:
                print(f"📋 Parent project detected: {parent_id}")
            
            return project_name, project_key, is_folder, parent_id
            
        except Exception as e:
            self.print_error(f"Error loading project info from {project_file}: {str(e)}")
            return None, None, None, None

    def load_json_data(self, source_project_id):
        """
        copy_fromサブフォルダからJSONファイルを読み込む
        """
        copy_from_dir = "copy_from\\project_setting"
        if not os.path.exists(copy_from_dir):
            self.print_error(f"Error: {copy_from_dir} directory does not exist.")
            return None, None

        items_file = os.path.join(copy_from_dir, f"project_{source_project_id}_items.json")
        relations_file = os.path.join(copy_from_dir, f"project_{source_project_id}_relations.json")

        if not os.path.exists(items_file):
            self.print_error(f"Error: {items_file} does not exist.")
            return None, None

        if not os.path.exists(relations_file):
            self.print_error(f"Error: {relations_file} does not exist.")
            return None, None

        # JSONファイルを読み込み
        with open(items_file, 'r', encoding='utf-8') as f:
            items_data = json.load(f)

        with open(relations_file, 'r', encoding='utf-8') as f:
            relations_data = json.load(f)

        print(f"Loaded {len(items_data)} items from {items_file}")
        print(f"Loaded {len(relations_data)} relations from {relations_file}")

        return items_data, relations_data

    def create_item_hierarchy(self, items_data):
        """
        アイテムの階層構造を解析し、作成順序を決定する
        """
        # parentのないアイテム（ルートアイテム）を最初に作成
        root_items = []
        child_items = []

        for item in items_data:
            location = item.get('location', {})
            if 'parent' not in location or location['parent'].get('item') is None:
                root_items.append(item)
            else:
                child_items.append(item)

        # ルートアイテムをsequence順でソート
        root_items.sort(key=lambda x: int(x.get('location', {}).get('sequence', '0')))
        
        # 子アイテムも階層順に整列（簡単な実装として、globalSortOrder順でソート）
        child_items.sort(key=lambda x: x.get('location', {}).get('globalSortOrder', 0))

        return root_items + child_items

    def process_attached_files(self, project_id, source_project_id,text):
        """
        Rich textに含まれる複数のimg srcタグを処理してファイルをアップロード、URLを置換する
        """
        print(f"🔄 Processing attached files for project (source) {source_project_id}")
        
        # <img>タグのsrc属性を抽出する正規表現パターン
        img_pattern = r'<img[^>]*?src\s*=\s*["\']([^"\']*?)["\'][^>]*?>'
        img_matches = re.findall(img_pattern, text, re.IGNORECASE | re.DOTALL)
        
        if not img_matches:
            print("ℹ️ No img tags found in text")
            return text
        
        print(f"📸 Found {len(img_matches)} image(s) to process")
        
        # テキストを置換していく
        new_text = text
        
        for i, img_url in enumerate(img_matches, 1):
            try:
                print(f"🔽 Processing image {i}/{len(img_matches)}: {img_url}")
                
                # URLからファイル名を抽出（パス情報を除いた部分）
                filename = os.path.basename(img_url.split('?')[0])  # クエリパラメータも除去
                if not filename:
                    filename = f'image_{i}'
                
                print(f"📁 Extracted filename: {filename}")
                #Extranct attachment ID from URL (assuming format /attachment/{id}/...)
                from urllib.parse import urlparse
                parsed_url = urlparse(img_url)
                path_parts = parsed_url.path.strip('/').split('/')
                                
                if len(path_parts) >= 2 :
                     attachment_id = path_parts[1]                
                else:
                    print(f"❌  Could not extract attachment ID from URL: {img_url}")
                    raise ValueError(f"Could not extract attachment ID from URL: {img_url}")
                
                # copy_fromディレクトリのファイルパスを構築
               
                saved_file_name = f'attachment_{source_project_id}_{attachment_id}_{filename}'
                copy_from_path = os.path.join('copy_from\\project_setting', saved_file_name)
                # ファイルの存在確認
                if not os.path.exists(copy_from_path):
                    print(f"❌ File not found in copy_from directory: {copy_from_path}")
                    continue
                
                print(f"✅ Found file: {copy_from_path} ({os.path.getsize(copy_from_path)} bytes)")
                
                # 1. Jama上でのファイル名とdescriptionを決める
                description = f'Copied image: {filename}'
                
                # 2. ProjectにATTACH FILEを登録・IDを作成する
                print(f"📤 Creating attachment entry in Jama...")
                attach_id = self.post_project_attachment(project_id, filename, description)
                print(f"📋 Created attachment ID: {attach_id}")
                
                # 3. アップロード前にファイルをリネーム（一時ファイル作成）
                import shutil
                temp_filename = filename
                temp_file_path = os.path.join(os.path.dirname(copy_from_path), temp_filename)
                shutil.copy2(copy_from_path, temp_file_path)
                
                # 4. ファイルをJamaプロジェクトにアップロードする
                print(f"⬆️ Uploading file to Jama...")
                upload_status = self.put_attachments_file(attach_id, temp_file_path)             
                os.remove(temp_file_path)
                
                print(f"✅ Upload successful (status: {upload_status})")
                
                
                # 4. アップロードしたファイルを参照するIDを取得
                attachment = self.get_attachment(attach_id)
                loadf_id = attachment['fields']['attachment']
                
                # 5. ファイル名をURLエンコード
                original_string = filename
                utf8_bytes = original_string.encode('utf-8')
                latin1_encoded = utf8_bytes.decode('latin-1')
                encoded_string = urllib.parse.quote(latin1_encoded)
                
                # 6. 新しいattach_urlを作成
                attach_url = self.JAMA_URL + '/attachment/' + str(loadf_id) + '/v/' + encoded_string
                print(f"🔗 New URL: {attach_url}")
                
                # 7. 元のsrc URLを新しいattach_urlに置換
                # srcの値部分のみを置換（引用符の種類に対応）
                old_src_patterns = [
                    f'src="{img_url}"',
                    f"src='{img_url}'",
                    f'src={img_url}'  # 引用符なしの場合
                ]
                
                replaced = False
                for pattern in old_src_patterns:
                    if pattern in new_text:
                        new_src = f'src="{attach_url}"'
                        new_text = new_text.replace(pattern, new_src)
                        print(f"🔄 Replaced: {pattern} -> {new_src}")
                        replaced = True
                        break
                
                if not replaced:
                    print(f"⚠️ Could not find exact URL pattern to replace: {img_url}")
                    
            except Exception as e:
                print(f"❌ Error processing image {i} ({img_url}): {e}")
                import traceback
                print(f"Error details: {traceback.format_exc()}")
                continue
        
        print(f"✅ Completed processing {len(img_matches)} images")
        return new_text


    def copy_items(self, items_data, target_project_id, source_project_id, type_id_mapping, picklist_option_mapping=None):
        """
        アイテムをターゲットプロジェクトにコピーする（itemTypeのマッピング付き）
        """
        print(f"Starting to copy {len(items_data)} items to project {target_project_id}")
        
        # アイテムを階層順に整列
        ordered_items = self.create_item_hierarchy(items_data)
        
        # 統計用カウンタ
        excluded_count = 0  # ATTACHMENT等の除外アイテム数
        processed_count = 0
        
        # 古いIDと新しいIDのマッピング
        old_id_to_new_id = {}
        created_items = []
        
        # Test関連のマッピング
        testplan_id_mapping = {}  # source_testplan_id: target_testplan_id
        testgroup_id_mapping = {}  # source_testgroup_id: target_testgroup_id
        testcycle_items = []  # TestCycle items for later processing
        testrun_items = []  # TestRun items for later processing

        for item in ordered_items:
            source_item_type = item['itemType']
            fields = item['fields'].copy()
            old_id = item["id"]
            processed_count += 1

            # itemType 22 (ATTACHMENT) はコピーから除外
            if source_item_type == 22:
                excluded_count += 1
                print(f"Skipping ATTACHMENT item {old_id} ({item.get('fields', {}).get('name', 'Unknown')})")
                continue

            # TestPlan(35) の処理
            if source_item_type == 35:  # TESTPLAN
                try:
                    testplan_name = item.get('fields', {}).get('name', f'TestPlan_{old_id}')
                    testplan_description = item.get('fields', {}).get('description', '')
                    
                    print(f"Creating TestPlan: '{testplan_name}' (old ID: {old_id})")
                    new_testplan_id = self.post_testplan(target_project_id, testplan_name, testplan_description)
                    
                    testplan_id_mapping[old_id] = new_testplan_id
                    old_id_to_new_id[old_id] = new_testplan_id
                    
                    created_items.append({
                        'old_id': old_id,
                        'new_id': new_testplan_id,
                        'name': testplan_name,
                        'source_item_type': source_item_type,
                        'target_item_type': source_item_type
                    })
                    
                    print(f"Created TestPlan: '{testplan_name}' (old ID: {old_id}, new ID: {new_testplan_id})")
                    continue
                    
                except Exception as e:
                    self.print_error(f"Error creating TestPlan {old_id}: {str(e)}")
                    continue
            
            # TestCycle(36)、TestRun(37)は後で処理するため保存
            if source_item_type == 36:  # TESTCYCLE
                testcycle_items.append(item)
                print(f"Saved TestCycle item {old_id} for later processing")
                continue
                
            if source_item_type == 37:  # TESTRUN
                testrun_items.append(item)
                print(f"Saved TestRun item {old_id} for later processing")
                continue

            # itemTypeをマッピング
            if source_item_type in type_id_mapping:
                target_item_type = type_id_mapping[source_item_type]
            else:
                self.print_warning(f"Warning: Item type {source_item_type} not found in type mapping. Skipping item {old_id}.")
                continue

            # child_item_type_idの必要性を確認）
            source_item_type_info = None
            requires_child_type = False
            # itemTypeの情報を取得
            for type_info in self.target_item_types_cache:
                if type_info.get('id') == target_item_type:
                    source_item_type_info = type_info
                    type_key = source_item_type_info.get('typeKey', '').lower()
                    # SetsやFolders等は必須でchild_item_type_idが必要、ここでフラグを立てておく
                    if 'set' in type_key or 'folder' in type_key:
                        requires_child_type = True
                    break
            
            # itemの親IDを取得と適切な配置
            parent_info = item.get("location", {}).get("parent", {})
            parent_id = parent_info.get("item")
            item_name = item.get('fields', {}).get('name', 'Unknown')
            item_type_name = source_item_type_info.get('typeKey', 'Unknown') if source_item_type_info else 'Unknown'

            if parent_id:  # 親IDが存在する場合
                new_parent_id = old_id_to_new_id.get(parent_id)
                if new_parent_id:
                    locationItem = {'item': new_parent_id}
                    print(f"📄 Placing item '{item_name}' ({item_type_name}) under parent {new_parent_id} (original: {parent_id})")
                else:
                    self.print_warning(f"Warning: Parent item {parent_id} not found in ID mapping for item {old_id}. Creating as root item.")
                    locationItem = {'project': target_project_id}
            else:  # ルートアイテムをコピーする場合(親IDがいない)
                locationItem = {'project': target_project_id}  # 親のID指定
                print(f"📄 Creating root item: '{item_name}' ({item_type_name})")

            itemTypeID = target_item_type  # マッピング後のtarget itemTypeIDを使用
            dct_fields = fields  #Fieldsをコピー
            
            # picklistオプション値マッピングと$が含まれるフィールドの為の検査
            updated_fields = {}
            for field_name, field_value in dct_fields.items():
                #type IDが変わった場合はフィールド名の$以降の数字が代わる
                if source_item_type != target_item_type:
                    # フィールド名が${source_item_type}で終わる場合、新しいitemTypeIDに置換
                    if field_name.endswith(f'${source_item_type}'):
                        base_name = field_name.rsplit('$', 1)[0]  # $より前の部分を取得
                        new_field_name = f'{base_name}${target_item_type}'
                        #print(f"🔄 Renamed field: '{field_name}' -> '{new_field_name}' for item {old_id} (value: {field_value} -> {mapped_value})")
                        field_name = new_field_name  # 以降の処理で新しいフィールド名を使用

                # フィールドがpicklistかどうかを調べる
                results = [
                    field 
                    for item in self.target_item_types_cache if item.get('id') == target_item_type
                    for field in item.get('fields', []) if field.get('name') == field_name
                ]
                target_field = results[0] if results else None
                if target_field is None:
                    print(f"Fieldmap {field_name} not found in item type {target_item_type}")
                    continue

                #  書き込み禁止フィールドはコピー対象から除外
                if target_field.get('readOnly',False):
                    if not target_field.get('readOnlyAllowApiOverwrite',True):
                        continue
                if target_field.get('pickList') is None: # picklistでないフィールドはマッピングの必要なし
                    updated_fields[field_name] = field_value
                    continue

                # picklistオプション値のマッピングを適用（マッピングが存在する場合のみ）
                mapped_value = field_value
                    
                # 整数値の場合：picklistマッピングが存在するもののみ処理
                if isinstance(field_value, int) and picklist_option_mapping and field_value in picklist_option_mapping:
                    mapped_value = picklist_option_mapping[field_value]
                    print(f"🔄 Mapped picklist option: {field_name} - {field_value} -> {mapped_value}")
                # リスト形式の場合：リスト内にマッピング対象がある場合のみ処理
                elif isinstance(field_value, list) and len(field_value) > 0 and picklist_option_mapping:
                    mapped_list = []
                    has_mapping = False
                    for i_val in field_value:
                        if isinstance(i_val, int) and i_val in picklist_option_mapping:
                            mapped_item = picklist_option_mapping[i_val]
                            mapped_list.append(mapped_item)
                            print(f"🔄 Mapped picklist option in list: {field_name} - {i_val} -> {mapped_item}")
                            has_mapping = True
                        else:
                            mapped_list.append(i_val)
                    if has_mapping:
                        mapped_value = mapped_list
                updated_fields[field_name] = mapped_value

            dct_fields = updated_fields
            description_field = item.get('fields', {}).get('description', '')
            
            #<img src= タグがdescriptionに含まれている場合、ファイルをJamaプロジェクトにアップロードしてURLを置換する
            if '<img' in description_field.lower() and 'src=' in description_field.lower():
               img_text = description_field
               new_text = self.process_attached_files(target_project_id,source_project_id, img_text)
               # descriptionのテキストを置換
               dct_fields['description'] = new_text

            # コピーできないフィールド値を削除
            import re
            fields_to_remove = ['documentKey', 'globalId','assignedTo']
            
            # フィールド名をチェックして除去対象を決定
            fields_to_delete = []
            for field_name in list(dct_fields.keys()):
                # 固定のフィールド名
                if field_name in fields_to_remove:
                    fields_to_delete.append(field_name)
                # releaseパターンのフィールド名（'release' または 'release$99'）
                elif re.match(r'^release$', field_name) or re.match(r'^release\$\d{2,3}$', field_name):
                    fields_to_delete.append(field_name)
            
            # 除去対象フィールドを削除
            for field in fields_to_delete:
                if field in dct_fields:
                    del dct_fields[field]

            child_type_id = item.get('childItemType', 0)
            
            # childItemTypeもマッピングが必要な場合
            if child_type_id and child_type_id in type_id_mapping:
                child_type_id = type_id_mapping[child_type_id]
            elif child_type_id:
                self.print_warning(f"Warning: Child item type {child_type_id} not found in type mapping for item {old_id}")
                child_type_id = 0
            
            # SetsやFoldersの場合、child_item_type_idが必須
            if requires_child_type and child_type_id == 0:
                # デフォルトのchild_item_type_idを探す
                default_child_type_id = None
                for type_id, target_id in type_id_mapping.items():
                    if target_id != target_item_type:  # 自分自身でないものを探す
                        default_child_type_id = target_id
                        break
                
                if default_child_type_id:
                    child_type_id = default_child_type_id
                    self.print_warning(f"Warning: Using default child item type {child_type_id} for {source_item_type_info.get('typeKey', 'unknown')} item {old_id}")
                else:
                    self.print_error(f"Error: Cannot create {source_item_type_info.get('typeKey', 'unknown')} item {old_id} without child item type. Skipping.")
                    continue

            # アイテムをコピー
            retry = True
            retry_count = 0
            while retry:
                try:
                    new_id = self.post_item(project=target_project_id, item_type_id=itemTypeID,
                                           child_item_type_id=child_type_id,
                                           location=locationItem, fields=dct_fields)

                    old_id_to_new_id[old_id] = new_id
                    created_items.append({
                        'old_id': old_id,
                        'new_id': new_id,
                        'name': item['fields'].get('name', 'Unknown'),
                        'source_item_type': source_item_type,
                        'target_item_type': target_item_type
                    })
                    
                    print(f"Created item: {item['fields'].get('name', 'Unknown')} (old ID: {old_id}, new ID: {new_id}, type: {source_item_type}->{target_item_type})")
                    retry = False

                except Exception as e:
                    retry_count += 1
                    if retry_count > 3:
                        self.print_error(f"Error creating item {old_id} ({item['fields'].get('name', 'Unknown')}) after {retry_count} retries: {str(e)}")
                        retry = False
                    else:
                        self.print_warning(f"Retry {retry_count} for item {old_id}: {str(e)}")
                        time.sleep(1)  # 1秒待ってリトライ

        # ========== Test関連の処理 ==========
        if testplan_id_mapping:
            print(f"\n=== Processing Test Plans, Groups, and Cases ===")
            
            # Test Group の処理
            for old_testplan_id, new_testplan_id in testplan_id_mapping.items():
                try:
                    print(f"Processing TestGroups for TestPlan {old_testplan_id} -> {new_testplan_id}")
                    
                    # TestGroup ファイルを読み込み
                    testgroups_file = os.path.join("copy_from\\project_setting", f"project_{source_project_id}_test_plan_{old_testplan_id}_testGroups.json")
                    
                    if os.path.exists(testgroups_file):
                        with open(testgroups_file, 'r', encoding='utf-8') as f:
                            testgroups = json.load(f)
                        
                        for testgroup in testgroups:
                            testgroup_id = testgroup.get('id')
                            testgroup_name = testgroup.get('name', '')
                            
                            # "Default Test Group" はスキップ
                            if testgroup_name == "Default Test Group":
                                print(f"  Skipping Default Test Group (ID: {testgroup_id})")
                                continue
                            
                            try:
                                print(f"  Creating TestGroup: '{testgroup_name}' (old ID: {testgroup_id})")
                                new_testgroup_id = self.post_testgroup(new_testplan_id, testgroup_name)
                                testgroup_id_mapping[testgroup_id] = new_testgroup_id
                                print(f"  Created TestGroup: '{testgroup_name}' (old ID: {testgroup_id} -> new ID: {new_testgroup_id})")
                                
                                # TestCase の処理
                                testcases_file = os.path.join("copy_from\\project_setting", f"project_{source_project_id}_testGroup_{testgroup_id}_testcases.json")
                                
                                if os.path.exists(testcases_file):
                                    with open(testcases_file, 'r', encoding='utf-8') as f:
                                        testcases = json.load(f)
                                    
                                    for testcase in testcases:
                                        old_testcase_id = testcase.get('id')
                                        new_testcase_id = old_id_to_new_id.get(old_testcase_id)
                                        
                                        if new_testcase_id:
                                            try:
                                                print(f"    Adding TestCase {old_testcase_id} -> {new_testcase_id} to TestGroup {new_testgroup_id}")
                                                self.post_testgroup_testcase(new_testplan_id, new_testgroup_id, new_testcase_id)
                                                print(f"    Added TestCase to TestGroup successfully")
                                            except Exception as e:
                                                print(f"    ❌ Failed to add TestCase {new_testcase_id} to TestGroup: {str(e)}")
                                        else:
                                            print(f"    ⚠️ TestCase ID {old_testcase_id} not found in mapping")
                                else:
                                    print(f"    ⚠️ TestCases file not found: {testcases_file}")
                                    
                            except Exception as e:
                                print(f"  ❌ Failed to create TestGroup '{testgroup_name}': {str(e)}")
                                continue
                    else:
                        print(f"  ⚠️ TestGroups file not found: {testgroups_file}")
                        
                except Exception as e:
                    print(f"❌ Error processing TestPlan {old_testplan_id}: {str(e)}")
                    continue
        
        # TestCycle の処理
        if testcycle_items:
            print(f"\n=== Processing Test Cycles ===")
            
            # TestRun から TestGroup と TestCycle の関連付けを集約
            testcycle_testgroup_mapping = {}  # testcycle_id: [testgroup_ids]
            testrun_status_mapping = {}  # testcycle_id: [testrun_statuses]
            
            for testrun_item in testrun_items:
                testrun_fields = testrun_item.get('fields', {})
                testcycle_id = testrun_fields.get('testCycle')
                testrun_status = testrun_fields.get('testRunStatus')
                testgroup_info = testrun_item.get('testGroup', [])
                
                if testcycle_id and len(testgroup_info) >= 2:
                    testgroup_id = testgroup_info[1]  # testGroup[1] がTestGroup ID
                    
                    if testcycle_id not in testcycle_testgroup_mapping:
                        testcycle_testgroup_mapping[testcycle_id] = set()
                        testrun_status_mapping[testcycle_id] = set()
                    
                    testcycle_testgroup_mapping[testcycle_id].add(testgroup_id)
                    if testrun_status:
                        testrun_status_mapping[testcycle_id].add(testrun_status)
            
            # TestCycle を作成
            for testcycle_item in testcycle_items:
                old_testcycle_id = testcycle_item.get('id')
                testcycle_fields = testcycle_item.get('fields', {})
                
                testcycle_name = testcycle_fields.get('name', f'TestCycle_{old_testcycle_id}')
                start_date = testcycle_fields.get('startDate')
                end_date = testcycle_fields.get('endDate')
                old_testplan_id = testcycle_fields.get('testPlan')
                
                new_testplan_id = testplan_id_mapping.get(old_testplan_id)
                
                if new_testplan_id and start_date and end_date:
                    # TestGroup IDsをマッピング
                    old_testgroup_ids = list(testcycle_testgroup_mapping.get(old_testcycle_id, []))
                    new_testgroup_ids = [testgroup_id_mapping.get(old_tg_id) for old_tg_id in old_testgroup_ids]
                    new_testgroup_ids = [tg_id for tg_id in new_testgroup_ids if tg_id is not None]
                    
                    # TestRun Statuses
                    testrun_statuses = list(testrun_status_mapping.get(old_testcycle_id, []))
                    
                    try:
                        print(f"Creating TestCycle: '{testcycle_name}' (old ID: {old_testcycle_id})")
                        new_testcycle_id = self.post_testplans_testcycles(
                            new_testplan_id, 
                            testcycle_name, 
                            start_date, 
                            end_date, 
                            testgroups_to_include=new_testgroup_ids if new_testgroup_ids else None
                        )
                        
                        
                        old_id_to_new_id[old_testcycle_id] = new_testcycle_id
                        print(f"Created TestCycle: '{testcycle_name}' (old ID: {old_testcycle_id} -> new ID: {new_testcycle_id})")
                        
                    except Exception as e:
                        print(f"❌ Failed to create TestCycle '{testcycle_name}': {str(e)}")
                        continue
                else:
                    missing_info = []
                    if not new_testplan_id: missing_info.append("TestPlan mapping")
                    if not start_date: missing_info.append("start_date")
                    if not end_date: missing_info.append("end_date")
                    print(f"⚠️ Skipping TestCycle {old_testcycle_id} - missing: {', '.join(missing_info)}")

        # 統計情報を表示
        eligible_items = len(items_data) - excluded_count
        print(f"Successfully created {len(created_items)} out of {eligible_items} eligible items")
        print(f"Total items in source: {len(items_data)} (excluded {excluded_count} ATTACHMENT items)")
        return old_id_to_new_id, created_items

    def copy_relations(self, relations_data, old_id_to_new_id, relationship_type_mapping=None):
        """
        関係（リレーション）をターゲットプロジェクトにコピーする
        relationship_type_mapping: 元のrelationship typeIDから新しいrelationship typeIDへのマッピング
        """
        print(f"Starting to copy {len(relations_data)} relations")
        
        created_relations = []
        skipped_relations = []
        
        for relation in relations_data:
            old_from_item = relation['fromItem']
            old_to_item = relation['toItem']
            old_relationship_type = relation['relationshipType']
            
            # 新しいIDに変換
            if old_from_item not in old_id_to_new_id:
                self.print_warning(f"Warning: fromItem {old_from_item} not found in ID mapping. Skipping relation.")
                skipped_relations.append({
                    'reason': 'fromItem_not_found',
                    'old_from_item': old_from_item,
                    'old_to_item': old_to_item,
                    'relationship_type': old_relationship_type
                })
                continue
            
            if old_to_item not in old_id_to_new_id:
                self.print_warning(f"Warning: toItem {old_to_item} not found in ID mapping. Skipping relation.")
                skipped_relations.append({
                    'reason': 'toItem_not_found',
                    'old_from_item': old_from_item,
                    'old_to_item': old_to_item,
                    'relationship_type': old_relationship_type
                })
                continue
            
            new_from_item = old_id_to_new_id[old_from_item]
            new_to_item = old_id_to_new_id[old_to_item]
            
            # Relationship typeのマッピング適用
            new_relationship_type = old_relationship_type
            if relationship_type_mapping and old_relationship_type in relationship_type_mapping:
                new_relationship_type = relationship_type_mapping[old_relationship_type]
                print(f"🔄 Mapping relationship type: {old_relationship_type} -> {new_relationship_type}")
            
            try:
                # 関係を作成
                created_relation_response = self.post_relationship(new_from_item, new_to_item, new_relationship_type)
                created_relations.append({
                    'old_from': old_from_item,
                    'old_to': old_to_item,
                    'new_from': new_from_item,
                    'new_to': new_to_item,
                    'old_relationship_type': old_relationship_type,
                    'new_relationship_type': new_relationship_type,
                    'new_relation_id': created_relation_response
                })
                
                mapping_note = f" (type mapped: {old_relationship_type}->{new_relationship_type})" if old_relationship_type != new_relationship_type else ""
                print(f"Created relation: {new_from_item} -> {new_to_item} (type: {new_relationship_type}){mapping_note}")

            except Exception as e:
                self.print_error(f"Error creating relation from {old_from_item} to {old_to_item} (type: {new_relationship_type}): {str(e)}")
                skipped_relations.append({
                    'reason': 'creation_error',
                    'old_from_item': old_from_item,
                    'old_to_item': old_to_item,
                    'relationship_type': old_relationship_type,
                    'mapped_relationship_type': new_relationship_type,
                    'error': str(e)
                })
                continue

        print(f"Successfully created {len(created_relations)} out of {len(relations_data)} relations")
        if skipped_relations:
            print(f"Skipped {len(skipped_relations)} relations due to errors")
            
        return created_relations, skipped_relations

    def create_new_project(self, project_name, project_key, existing_projects=None, is_folder=False, parent_id=None, project_folder_mapping=None):
        """
        新しいプロジェクトを作成する（フォルダ構造を考慮した処理）
        """
        try:
            # 既存プロジェクトをチェック
            folder_status = "📁 PROJECT FOLDER" if is_folder else "📄 PROJECT"
            print(f"Creating {folder_status}: '{project_name}' (key: '{project_key}')...")
            
            # 事前に取得したプロジェクト一覧で同じキーがないかチェック
            if existing_projects:
                for existing_project in existing_projects:
                    existing_fields = existing_project.get('fields', {})
                    existing_key = existing_fields.get('projectKey', '')
                    if existing_key == project_key:
                        existing_id = existing_project.get('id')
                        existing_name = existing_fields.get('name', 'Unknown')
                        self.print_warning(f"⚠️ Project with key '{project_key}' already exists (ID: {existing_id}, Name: '{existing_name}')")
                        self.print_warning(f"Using existing {folder_status.lower()}: '{existing_name}' (ID: {existing_id})")
                        return existing_id  # 既存プロジェクトのIDを返してマッピングに使用
            
            # フォルダプロジェクトの場合の処理
            if is_folder:
                print(f"📁 Creating project folder: '{project_name}'")
                # フォルダプロジェクトを作成し、IDマッピングを保持
                created_project_id = self.post_project(project_key, project_name, is_folder=True)
                print(f"📁 Created project folder '{project_name}' (key: '{project_key}') with ID: {created_project_id}")
                return created_project_id
            
            # 通常のプロジェクトの場合
            if parent_id and project_folder_mapping:
                parent_project_id = parent_id  # parent_idは直接親IDの整数値
                if parent_project_id in project_folder_mapping:
                    # 親フォルダの新しいIDを取得
                    new_parent_id = project_folder_mapping[parent_project_id]
                    print(f"📄 Creating project under folder {new_parent_id} (original: {parent_project_id})")
                    # 親フォルダを指定してプロジェクト作成（Jama APIによってはサポートされていない可能性がある）
                    # 現在は通常のプロジェクトとして作成
                    created_project_id = self.post_project(project_key, project_name,is_folder=False, parent_id=new_parent_id)
                else:
                    self.print_warning(f"Warning: Parent project {parent_project_id} not found in project folder mapping. Creating as root project.")
                    created_project_id = self.post_project(project_key, project_name)
            else:
                # 親がない、またはマッピングがない場合
                created_project_id = self.post_project(project_key, project_name)
            
            print(f"📄 Created project '{project_name}' (key: '{project_key}') with ID: {created_project_id}")
            return created_project_id
        
        except Exception as e:
            self.print_error(f"Error creating project '{project_name}': {str(e)}")
            return None

    def copy_project(self, source_project_id, new_project_name, project_key, existing_projects=None, is_folder=False, parent_id=None, project_folder_mapping=None, type_id_mapping=None, relationship_type_mapping=None, picklist_option_mapping=None):
        """
        プロジェクトをコピーする全体のプロセス（フォルダ構造を考慮、マッピング再利用）
        """
        folder_status = "📁 PROJECT FOLDER" if is_folder else "📄 PROJECT"
        print(f"Copying {folder_status} {source_project_id} to new project '{new_project_name}' (key: '{project_key}')")
        
        # JSONデータを読み込み
        items_data, relations_data = self.load_json_data(source_project_id)
        if items_data is None or relations_data is None:
            return False, None

        # 新しいプロジェクトを作成（フォルダ構造考慮）
        target_project_id = self.create_new_project(new_project_name, project_key, existing_projects, is_folder, parent_id, project_folder_mapping)
        if target_project_id is None:
            # プロジェクトの作成が失敗した場合
            self.print_warning(f"Project creation failed for '{new_project_name}' (key: '{project_key}')")
            return False, None
        
        print(f"Target project ID: {target_project_id}")

        # フォルダプロジェクトの場合、アイテムや関係のコピーはスキップ
        if is_folder:
            print("📁 Project folder created successfully. Skipping items and relations copy.")
            return True, target_project_id

        # マッピングが提供されていない場合はエラー
        if type_id_mapping is None or relationship_type_mapping is None:
            self.print_error("Error: Type mappings must be provided.")
            return False, None

        # アイテムをコピー
        old_id_to_new_id, created_items = self.copy_items(items_data, target_project_id, source_project_id,type_id_mapping, picklist_option_mapping)
        
        if not created_items:
            self.print_warning("No items were created. Aborting relation creation.")
            return False

        # 関係をコピー（relationship typeマッピング付き）
        created_relations, skipped_relations = self.copy_relations(relations_data, old_id_to_new_id, relationship_type_mapping)

        print("\n=== Copy Summary ===")
        print(f"Items created: {len(created_items)}")
        print(f"Relations created: {len(created_relations)}")
        if skipped_relations:
            print(f"Relations skipped: {len(skipped_relations)}")

        # 結果をJSONファイルに保存
        copy_result = {
            "source_project_id": source_project_id,
            "target_project_id": target_project_id,
            "target_project_name": new_project_name,
            "copy_date": datetime.now().isoformat(),
            "id_mapping": old_id_to_new_id,
            "created_items": created_items,
            "created_relations": created_relations,
            "skipped_relations": skipped_relations
        }

        # outputフォルダを作成
        os.makedirs("output", exist_ok=True)
        result_filename = f"output/copy_result_{source_project_id}_to_{target_project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(result_filename, 'w', encoding='utf-8') as f:
            json.dump(copy_result, f, indent=4, sort_keys=True, separators=(',', ': '), ensure_ascii=False)
        
        print(f"Copy result saved to {result_filename}")
        return True, target_project_id

def main():
    # outputフォルダがなければ作成
    os.makedirs("output", exist_ok=True)
    
    # ログファイルを開く（実行日時をファイル名に含める）
    log_filename = f"output/copy_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file = open(log_filename, 'w', encoding='utf-8')
    
    # 標準出力をファイルにも出力するように設定
    original_stdout = sys.stdout
    sys.stdout = TeeOutput(log_file)
    
    try:
        # 実行開始ログ
        print("=" * 80)
        print(f"JamaCopyProject - Automatic project copying from copy_from folder")
        print(f"Execution started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        print("Scanning copy_from folder for available projects...")
        
        # copy_fromフォルダの存在確認
        if not os.path.exists("copy_from"):
            print("\033[91mError: 'copy_from' directory does not exist. Please create it and put your JSON files there.\033[0m")
            return

        copier = JamaProjectCopier()
        
        # 利用可能なプロジェクトをスキャン
        available_projects = copier.scan_copy_from_projects()
        
        if not available_projects:
            print("No complete project files found in copy_from folder.")
            print("Please ensure you have the following files for each project:")
            print("- project_XXX.json")
            print("- project_XXX_items.json")
            print("- project_XXX_relations.json")
            return
        
        print(f"Found {len(available_projects)} complete project(s): {available_projects}")
        
        # プロジェクト情報を読み込み、フォルダ構造を解析
        project_infos = {}
        folder_projects = []
        regular_projects = []
        project_folder_mapping = {}  # 元のプロジェクトID -> 新しいプロジェクトID
        
        for source_project_id in available_projects:
            project_name, project_key, is_folder, parent_id = copier.load_project_info(source_project_id)
            if project_name is None:
                print(f"Failed to load project info for {source_project_id}")
                continue
            
            project_infos[source_project_id] = {
                'name': project_name,
                'key': project_key,
                'is_folder': is_folder,
                'parent_id': parent_id
            }
            
            if is_folder:
                folder_projects.append(source_project_id)
            else:
                regular_projects.append(source_project_id)
        
        print(f"📋 Project structure: {len(folder_projects)} folders, {len(regular_projects)} regular projects")
        
        # コピー先の既存プロジェクト一覧を一度だけ取得
        print("\n=== Getting Target Projects List ===")
        try:
            existing_projects = list(copier.get_projects())
            print(f"Found {len(existing_projects)} existing projects in target")
        except Exception as e:
            copier.print_error(f"Failed to get existing projects: {str(e)}")
            existing_projects = None
        
        # 使用されているタイプを収集し、マッピングを一度だけ作成
        used_item_types, used_relationship_types = copier.collect_used_types_from_projects({k: v for k, v in project_infos.items() if not v.get('is_folder')})
        
        if not used_item_types and not used_relationship_types:
            print("📋 No items or relationships found in regular projects. Only folder projects will be created.")
            type_id_mapping = {}
            created_types = []
            relationship_type_mapping = {}
            picklist_option_mapping = {}  # 空の辞書として初期化
        else:
            type_id_mapping, created_types, relationship_validation_success, relationship_type_mapping, picklist_id_mapping, picklist_option_mapping = copier.create_filtered_type_mappings(used_item_types, used_relationship_types)
            
            if not relationship_validation_success:
                print("🚫 Type mapping validation failed. Aborting all project copying.")
                return
            
            print(f"✅ Successfully created mappings: {len(type_id_mapping)} item types, {len(relationship_type_mapping)} relationship types, {len(picklist_option_mapping)} picklist options")
        
        # 各プロジェクトをコピー（フォルダー優先、マッピング再利用）
        successful_copies = []
        failed_copies = []
        
        # 1. フォルダプロジェクトを最初に作成
        for source_project_id in folder_projects:
            print(f"\n=== Processing Project Folder {source_project_id} ===")
            
            project_info = project_infos[source_project_id]
            success, target_project_id = copier.copy_project(
                source_project_id, 
                project_info['name'], 
                project_info['key'],
                existing_projects=existing_projects,
                is_folder=True,
                parent_id=project_info.get('parent_id'),
                project_folder_mapping=project_folder_mapping,
                type_id_mapping=type_id_mapping,
                relationship_type_mapping=relationship_type_mapping,
                picklist_option_mapping=picklist_option_mapping
            )
            
            if success:
                project_folder_mapping[source_project_id] = target_project_id
                successful_copies.append({
                    'source_id': source_project_id,
                    'target_id': target_project_id,
                    'name': project_info['name'],
                    'key': project_info['key'],
                    'is_folder': True
                })
                print(f"📁 Successfully created project folder {source_project_id} -> {target_project_id}")
            else:
                failed_copies.append(source_project_id)
                print(f"📁 Failed to create project folder {source_project_id}")
        
        # 2. 通常のプロジェクトを作成
        for source_project_id in regular_projects:
            print(f"\n=== Processing Regular Project {source_project_id} ===")
            
            project_info = project_infos[source_project_id]
            success, target_project_id = copier.copy_project(
                source_project_id,
                project_info['name'],
                project_info['key'],
                existing_projects=existing_projects,
                is_folder=False,
                parent_id=project_info.get('parent_id'),
                project_folder_mapping=project_folder_mapping,
                type_id_mapping=type_id_mapping,
                relationship_type_mapping=relationship_type_mapping,
                picklist_option_mapping=picklist_option_mapping
            )
            
            if success:
                successful_copies.append({
                    'source_id': source_project_id,
                    'target_id': target_project_id,
                    'name': project_info['name'],
                    'key': project_info['key'],
                    'is_folder': False
                })
                print(f"📄 Successfully copied project {source_project_id} -> {target_project_id}")
            else:
                failed_copies.append(source_project_id)
                print(f"📄 Failed to copy project {source_project_id}")
        
        print(f"\n=== Final Results ===")
        print(f"Successful copies: {len(successful_copies)}")
        for copy_info in successful_copies:
            status_icon = "📁" if copy_info.get('is_folder') else "📄"
            item_type = "FOLDER" if copy_info.get('is_folder') else "PROJECT"
            print(f"  {status_icon} {item_type}: {copy_info['name']} ({copy_info['key']}): {copy_info['source_id']} -> {copy_info['target_id']}")
        
        if failed_copies:
            print(f"Failed copies: {len(failed_copies)}")
            for failed_id in failed_copies:
                failed_info = project_infos.get(failed_id)
                if failed_info:
                    status_icon = "📁" if failed_info.get('is_folder') else "📄"
                    item_type = "FOLDER" if failed_info.get('is_folder') else "PROJECT"
                    print(f"  {status_icon} {item_type}: Project {failed_id} ({failed_info.get('name', 'Unknown')})")
                else:
                    print(f"  - Project {failed_id}")
        else:
            print("All projects copied successfully! 🎉")
        
        # 実行終了ログ
        print("=" * 80)
        print(f"Execution completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Log file saved: {log_filename}")
        print("=" * 80)
        
    except Exception as e:
        print("=" * 80)
        print(f"ERROR: An unexpected error occurred: {str(e)}")
        import traceback
        print(traceback.format_exc())
        print(f"Execution failed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
    finally:
        # 標準出力を元に戻してログファイルを閉じる
        sys.stdout = original_stdout
        log_file.close()
        print(f"Process completed. Log saved to: {log_filename}")

if __name__ == '__main__':
    main()