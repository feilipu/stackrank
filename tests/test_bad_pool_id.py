def test_bad_pool_id(client):
    for path in ("/pool/add/-1", "/pool/add/999999"):
        r = client.post(path, follow_redirects=False)
        assert r.status_code != 500