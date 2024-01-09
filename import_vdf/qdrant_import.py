import os
from dotenv import load_dotenv
import pandas as pd
from qdrant_client import QdrantClient
from export.util import extract_numerical_hash
from import_vdf.vdf_import import ImportVDF
from qdrant_client.http.models import VectorParams, Distance, PointStruct, UpdateStatus

load_dotenv()


class ImportQdrant(ImportVDF):
    def __init__(self, args):
        # call super class constructor
        super().__init__(args)
        self.client = QdrantClient(
            url=self.args["url"], api_key=self.args["qdrant_api_key"]
        )

    def upsert_data(self):
        # we know that the self.vdf_meta["indexes"] is a list
        for index_name, index_meta in self.vdf_meta["indexes"].items():
            # load data
            print(f"Importing data for index '{index_name}'")
            for namespace_meta in index_meta:
                data_path = namespace_meta["data_path"]
                # list indexes
                collections = [
                    x.name for x in self.client.get_collections().collections
                ]
                # check if index exists
                new_collection_name = index_name + (
                    f"_{namespace_meta['namespace']}"
                    if namespace_meta["namespace"]
                    else ""
                )
                if new_collection_name not in collections:
                    # create index
                    try:
                        self.client.create_collection(
                            collection_name=new_collection_name,
                            vectors_config=VectorParams(
                                size=namespace_meta["dimensions"],
                                distance=(
                                    namespace_meta["metric"]
                                    if "metric" in namespace_meta
                                    else Distance.COSINE
                                ),
                            ),
                        )
                    except Exception as e:
                        print(f"Failed to create index '{new_collection_name}'", e)
                        return
                prev_vector_count = self.client.get_collection(
                    collection_name=new_collection_name
                ).vectors_count
                if prev_vector_count > 0:
                    print(
                        f"Index '{new_collection_name}' has {prev_vector_count} vectors before import"
                    )
                # Load the data from the parquet files
                parquet_files = sorted(
                    [
                        file
                        for file in os.listdir(data_path)
                        if file.endswith(".parquet")
                    ]
                )

                vectors = {}
                metadata = {}
                for file in parquet_files:
                    file_path = os.path.join(data_path, file)
                    df = pd.read_parquet(file_path)
                    vectors.update(
                        {row["id"]: row["vector"] for _, row in df.iterrows()}
                    )
                    metadata.update(
                        {
                            row["id"]: {
                                key: value
                                for key, value in row.items()
                                if key != "id" and key != "vector"
                            }
                            for _, row in df.iterrows()
                        }
                    )
                vectors = {k: v.tolist() for k, v in vectors.items()}
                response = self.client.upsert(
                    collection_name=new_collection_name,
                    points=[
                        PointStruct(
                            id=int(idx)
                            if idx.isdigit()
                            else extract_numerical_hash(idx),
                            vector=vectors[idx],
                            payload=metadata.get(idx, {}),
                        )
                        for idx in vectors.keys()
                    ],
                    wait=True,
                )
                if response.status != UpdateStatus.COMPLETED:
                    print(
                        f"Failed to upsert data for collection '{new_collection_name}'"
                    )
                    continue
                vector_count = self.client.get_collection(
                    collection_name=new_collection_name
                ).vectors_count
                print(
                    f"Index '{new_collection_name}' has {vector_count} vectors after import"
                )
                print(f"{vector_count - prev_vector_count} vectors were imported")
        print("Data import completed successfully.")